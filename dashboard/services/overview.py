"""Guild overview aggregation for the relay dashboard home.

One round trip that answers "is this server's relay actually forwarding, and
what happened lately". Every section is built independently so the router can
gather them with ``return_exceptions=True`` and null out whatever failed - one
slow or broken collection must never blank the whole page.

Read-only by design. Nothing here writes and nothing creates an index; the
queries ride the indexes ``GuildManager._ensure_indexes`` already creates
(``message_logs`` on ``(guild_id, forwarded_at)`` with a 90-day TTL,
``denial_counters`` on ``(guild_id, date)`` with a 90-day TTL).

Data sources, and the bot-side writers that fill them:

  - ``guild_settings``   per-guild config + the embedded ``rules`` array, plus
                         the persistent ``lifetime_forwarded`` counter
                         (``GuildManager.log_forwarded_messages``)
  - ``message_logs``     one doc per forwarded message, 90-day TTL
                         (``GuildManager.log_forwarded_messages``)
  - ``denial_counters``  per-(guild, UTC day, reason) blocked buckets, 90-day
                         TTL (``GuildManager.record_denial``)
  - ``daily_counters``   per-(guild, UTC day) forwarded quota counter, 3-day TTL
  - ``premium_state``    derived premium status (``PremiumManager``)
  - ``audit_logs``       admin action trail (panel + dashboard writes)

``daily_counters`` is deliberately NOT the source of the trend: it only keeps
about three days, so a 30-day series drawn from it would be mostly holes.
Today's figure is read from ``message_logs`` for the same reason the stats API
does - the two pages must never disagree about the same number.

Every stored guild id is a STRING. Querying with an int matches nothing,
silently.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from dashboard import db
from dashboard.services.premium import get_guild_limits, get_premium_status

from storage.log import get_logger

logger = get_logger("dashboard.services.overview")

#: How far back the trend and the per-rule / blocked windows look.
TREND_DAYS = 30

#: Routes surfaced on the overview. The full list lives on the Rules page.
ROUTES_LIMIT = 6

#: The only reasons the bot ever records. Mirrors the ``METRIC_*`` constants in
#: ``commands/forward/forward.py``; ``record_denial`` is called with exactly
#: these three. Order is the order the overview lists them in when counts tie.
BLOCK_REASONS: tuple[str, ...] = ("perm_failure", "daily_limit_hit", "rate_limited")


# ── Small shared helpers ─────────────────────────────────────────────────────


def _iso(value: Any) -> str | None:
    """Datetime -> ISO-8601 string. Naive values are read as UTC (that is how
    every writer in this bot stores them). Anything else becomes None."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _date_range(start: datetime, end: datetime) -> list[str]:
    """Inclusive list of ``YYYY-MM-DD`` strings from ``start`` to ``end`` (UTC).

    Same helper the stats API uses, so both series are gap-filled identically:
    a chart drawn only from the days that had traffic reports a cadence the
    server never had.
    """
    out: list[str] = []
    day = start.date()
    last = end.date()
    while day <= last:
        out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def _window_start(now: datetime, days: int = TREND_DAYS) -> datetime:
    return now - timedelta(days=days)


def _as_str_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


# ── Traffic ──────────────────────────────────────────────────────────────────


async def build_traffic(gid: str, settings_doc: dict) -> dict:
    """``TrafficOverview`` - the 30-day forwarded/blocked series and today's cap.

    ``lifetime`` falls back to the visible history exactly the way the stats API
    does. The bot seeds ``lifetime_forwarded`` on its first forward after that
    feature shipped, so before then the count of surviving ``message_logs`` rows
    is the same floor the bot itself will seed.
    """
    now = datetime.now(timezone.utc)
    cutoff = _window_start(now)
    cutoff_date = cutoff.date().isoformat()

    facet_pipeline = [
        {"$match": {"guild_id": gid, "forwarded_at": {"$gte": cutoff}}},
        {
            "$facet": {
                "daily": [
                    {
                        "$group": {
                            "_id": {
                                "$dateToString": {
                                    "format": "%Y-%m-%d",
                                    "date": "$forwarded_at",
                                    "timezone": "UTC",
                                }
                            },
                            "count": {"$sum": 1},
                        }
                    },
                ],
                "total": [{"$count": "n"}],
            }
        },
    ]

    cursor = await db.message_logs().aggregate(facet_pipeline)
    facet_docs = await cursor.to_list(length=1)
    facet = facet_docs[0] if facet_docs else {}

    total_rows = facet.get("total", [])
    forwarded_30d = int(total_rows[0]["n"]) if total_rows else 0
    daily_forwarded = {row["_id"]: int(row["count"]) for row in facet.get("daily", [])}

    daily_blocked: dict[str, int] = {}
    blocked_30d = 0
    denial_cursor = db.denial_counters().find(
        {"guild_id": gid, "date": {"$gte": cutoff_date}},
        {"_id": 0, "date": 1, "count": 1},
    )
    async for doc in denial_cursor:
        count = int(doc.get("count", 0))
        date = doc.get("date")
        blocked_30d += count
        if date:
            daily_blocked[date] = daily_blocked.get(date, 0) + count

    daily = [
        {
            "date": day,
            "forwarded": daily_forwarded.get(day, 0),
            "blocked": daily_blocked.get(day, 0),
        }
        for day in _date_range(cutoff, now)
    ]

    days_active = sum(1 for value in daily_forwarded.values() if value > 0)
    # Averaged over the days something was actually forwarded. Dividing by a flat
    # 30 would read as a collapse in traffic on a server whose source channels
    # are simply quiet most of the week.
    avg_per_active_day = round(forwarded_30d / days_active, 1) if days_active else 0.0

    peak_row = max(daily, key=lambda row: row["forwarded"], default=None)
    peak = (
        {"date": peak_row["date"], "forwarded": peak_row["forwarded"]}
        if peak_row and peak_row["forwarded"] > 0
        else None
    )

    limits, last_doc = await asyncio.gather(
        get_guild_limits(gid),
        db.message_logs().find_one(
            {"guild_id": gid, "success": True},
            {"_id": 0, "forwarded_at": 1},
            sort=[("forwarded_at", -1)],
        ),
    )

    lifetime = (settings_doc or {}).get("lifetime_forwarded")
    if lifetime is None:
        lifetime = await db.message_logs().count_documents(
            {"guild_id": gid, "success": True}
        )

    today_key = now.strftime("%Y-%m-%d")

    return {
        "days": TREND_DAYS,
        "daily": daily,
        "forwarded_30d": forwarded_30d,
        "blocked_30d": blocked_30d,
        "lifetime": int(lifetime),
        "today_forwarded": daily_forwarded.get(today_key, 0),
        "daily_limit": int(limits["daily_limit"]),
        "days_active": days_active,
        "avg_per_active_day": avg_per_active_day,
        "peak": peak,
        "last_forward_at": _iso((last_doc or {}).get("forwarded_at")),
    }


# ── Rules ────────────────────────────────────────────────────────────────────


async def build_rules(gid: str, settings_doc: dict) -> dict:
    """``RulesOverview`` - the configured routes and how much each one carried.

    Only rules that still exist in the config are listed. A rule deleted since
    its messages were forwarded still has rows in ``message_logs``; the stats
    page reports those as "Deleted rule", but the overview is about the setup
    as it stands today, so they are counted in the traffic totals and left out
    of the route list.
    """
    now = datetime.now(timezone.utc)
    cutoff = _window_start(now)

    per_rule_cursor = await db.message_logs().aggregate([
        {"$match": {"guild_id": gid, "forwarded_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$rule_id", "count": {"$sum": 1}}},
    ])
    per_rule = {row["_id"]: int(row["count"]) async for row in per_rule_cursor}

    limits = await get_guild_limits(gid)

    rules = (settings_doc or {}).get("rules") or []
    active = [rule for rule in rules if rule.get("is_active")]

    cross_guild = 0
    newest: datetime | None = None
    for rule in rules:
        destination_guild = _as_str_id(rule.get("destination_guild_id"))
        if destination_guild is not None and destination_guild != gid:
            cross_guild += 1
        created = rule.get("created_at")
        if isinstance(created, datetime) and (newest is None or created > newest):
            newest = created

    def _route(rule: dict) -> dict:
        destination_guild = _as_str_id(rule.get("destination_guild_id"))
        return {
            "rule_id": str(rule.get("rule_id") or ""),
            "rule_name": rule.get("rule_name") or "Unnamed rule",
            "source_channel_id": _as_str_id(rule.get("source_channel_id")) or "",
            "destination_channel_id": _as_str_id(rule.get("destination_channel_id")) or "",
            "destination_guild_id": destination_guild or "",
            "cross_guild": destination_guild is not None and destination_guild != gid,
            "is_active": bool(rule.get("is_active")),
            "forwarded_30d": int(per_rule.get(rule.get("rule_id"), 0)),
        }

    routes = [_route(rule) for rule in rules]
    # Active first, then by how much each carried. A paused rule that used to be
    # busy must not push a live rule off the list.
    routes.sort(key=lambda row: (not row["is_active"], -row["forwarded_30d"]))

    idle_active = sum(
        1 for rule in active if int(per_rule.get(rule.get("rule_id"), 0)) == 0
    )

    return {
        "total": len(rules),
        "active": len(active),
        "paused": len(rules) - len(active),
        "cross_guild": cross_guild,
        "max_rules": int(limits["max_rules"]),
        "idle_active": idle_active,
        "newest_at": _iso(newest),
        "routes": routes[:ROUTES_LIMIT],
    }


# ── Delivery ─────────────────────────────────────────────────────────────────


async def build_delivery(gid: str) -> dict:
    """``DeliveryOverview`` - why messages were not forwarded, and when last.

    Three reasons exist and no more: the bot calls ``record_denial`` from
    exactly three places. An unknown reason is still passed through rather than
    dropped, so a new bot-side counter shows up here instead of vanishing.
    """
    now = datetime.now(timezone.utc)
    cutoff_date = _window_start(now).date().isoformat()

    counts: dict[str, int] = {}
    last_seen: dict[str, str] = {}
    total = 0

    cursor = db.denial_counters().find(
        {"guild_id": gid, "date": {"$gte": cutoff_date}},
        {"_id": 0, "date": 1, "reason": 1, "count": 1},
    )
    async for doc in cursor:
        reason = doc.get("reason") or "unknown"
        count = int(doc.get("count", 0))
        date = doc.get("date")
        total += count
        counts[reason] = counts.get(reason, 0) + count
        if date and (reason not in last_seen or date > last_seen[reason]):
            last_seen[reason] = date

    def _order(reason: str) -> int:
        return BLOCK_REASONS.index(reason) if reason in BLOCK_REASONS else len(BLOCK_REASONS)

    reasons = [
        {"reason": reason, "count": count, "last_date": last_seen.get(reason)}
        for reason, count in counts.items()
    ]
    reasons.sort(key=lambda row: (-row["count"], _order(row["reason"])))

    return {
        "blocked_30d": total,
        "undeliverable_30d": counts.get("perm_failure", 0),
        "reasons": reasons,
    }


# ── Plan ─────────────────────────────────────────────────────────────────────


async def build_plan(gid: str) -> dict:
    """``PlanOverview`` - premium tier and the caps it buys."""
    status, limits = await asyncio.gather(
        get_premium_status(gid),
        get_guild_limits(gid),
    )
    return {
        "tier": status["tier"],
        "tiers": status["tiers"],
        "is_premium": bool(status["is_premium"]),
        "expires_at": _iso(status.get("expires_at")),
        "max_rules": int(limits["max_rules"]),
        "daily_limit": int(limits["daily_limit"]),
    }


# ── Config ───────────────────────────────────────────────────────────────────


async def build_config(gid: str, settings_doc: dict) -> dict:
    """``ConfigOverview`` - how this server is set up, plus the last change made.

    ``has_config`` distinguishes "the bot has never written a settings document
    for this server" from "everything in it is at its default", which look the
    same once every field has been defaulted.
    """
    doc = settings_doc or {}
    features = doc.get("features") or {}
    inbound = doc.get("inbound_allowed_guilds") or []

    last_change = None
    entry = await db.audit_logs().find_one({"guild_id": gid}, sort=[("_id", -1)])
    if entry:
        last_change = {
            "category": entry.get("category") or "",
            "action": entry.get("action") or "",
            "actor_id": str(entry.get("actor_id") or ""),
            "at": _iso(entry.get("created_at")),
        }

    return {
        "has_config": bool(doc),
        "is_enabled": bool(doc.get("is_enabled", True)),
        "forwarding_enabled": bool(features.get("forwarding_enabled", True)),
        "notify_on_error": bool(features.get("notify_on_error", True)),
        "log_channel_id": _as_str_id(doc.get("master_log_channel_id")),
        "manager_role_id": _as_str_id(doc.get("manager_role_id")),
        "inbound_allowed_guilds": [str(g) for g in inbound],
        "last_change": last_change,
    }


# ── Feature status rail ──────────────────────────────────────────────────────


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def build_features(
    settings_doc: dict,
    *,
    traffic: dict | None,
    rules: dict | None,
    delivery: dict | None,
    config: dict | None,
) -> list[dict]:
    """One ``FeatureStatus`` per surface, in the order the home page shows them.

    "needs_setup" is the state that earns this rail: switched on, looking alive,
    and missing the one thing it cannot run without. A relay that reports itself
    online while quietly forwarding nothing - master switch on but no active
    rules, or every destination channel gone - is the complaint this answers.

    ``settings_key`` values match the rail slugs in the settings page, which
    reads ``?s=<key>``.
    """
    doc = settings_doc or {}
    feature_flags = doc.get("features") or {}
    has_config = bool(doc)

    forwarding_on = bool(doc.get("is_enabled", True)) and bool(
        feature_flags.get("forwarding_enabled", True)
    )
    active_rules = (rules or {}).get("active")
    forwarded_30d = (traffic or {}).get("forwarded_30d")

    features: list[dict] = []

    # -- Message forwarding --------------------------------------------------
    if not has_config:
        state, detail = "needs_setup", "This server has no relay settings yet"
    elif not forwarding_on:
        state, detail = "off", "Turned off"
    elif not active_rules:
        state, detail = "needs_setup", "No active rules yet"
    else:
        state = "on"
        if isinstance(forwarded_30d, int) and forwarded_30d > 0:
            detail = f"{_plural(forwarded_30d, 'message')} in 30 days"
        else:
            detail = f"{_plural(int(active_rules), 'rule')} watching, nothing matched yet"
    features.append({
        "key": "forwarding",
        "label": "Message forwarding",
        "state": state,
        "detail": detail,
        "settings_key": "forwarding",
    })

    # -- Rule delivery -------------------------------------------------------
    # Undeliverable messages are the failure that looks like nothing at all: the
    # rule is on, the source is busy, and the destination channel is gone or the
    # bot cannot post there.
    undeliverable = (delivery or {}).get("undeliverable_30d")
    idle_active = (rules or {}).get("idle_active")
    if not forwarding_on or not active_rules:
        state, detail = "off", "Nothing to deliver"
    elif isinstance(undeliverable, int) and undeliverable > 0:
        state = "needs_setup"
        detail = f"{_plural(undeliverable, 'message')} could not be delivered"
    elif isinstance(idle_active, int) and idle_active > 0:
        state = "on"
        detail = f"{_plural(idle_active, 'rule')} carried nothing in 30 days"
    else:
        state, detail = "on", "No delivery problems in 30 days"
    features.append({
        "key": "delivery",
        "label": "Rule delivery",
        "state": state,
        "detail": detail,
        "settings_key": None,
    })

    # -- Cross-server forwarding --------------------------------------------
    # An empty allowlist is the safe default, not a fault, so it reads as "off"
    # rather than "needs setup". Nothing is broken - nothing is allowed in.
    allowed = (config or {}).get("inbound_allowed_guilds")
    if not allowed:
        state, detail = "off", "No other server may forward in"
    else:
        state = "on"
        detail = f"{_plural(len(allowed), 'server')} may forward in"
    features.append({
        "key": "cross_server",
        "label": "Cross-server forwarding",
        "state": state,
        "detail": detail,
        "settings_key": "cross_server",
    })

    # -- Error notices -------------------------------------------------------
    if not bool(feature_flags.get("notify_on_error", True)):
        state, detail = "off", "Turned off"
    else:
        state, detail = "on", "Posts a notice when a forward is blocked"
    features.append({
        "key": "notify_on_error",
        "label": "Error notices",
        "state": state,
        "detail": detail,
        "settings_key": "forwarding",
    })

    # -- Activity log --------------------------------------------------------
    if not doc.get("master_log_channel_id"):
        state, detail = "off", "No log channel set"
    else:
        state, detail = "on", "Writing to your log channel"
    features.append({
        "key": "logging",
        "label": "Activity log",
        "state": state,
        "detail": detail,
        "settings_key": "logging",
    })

    # -- Who can manage ------------------------------------------------------
    if not doc.get("manager_role_id"):
        state, detail = "off", "Manage Server holders only"
    else:
        state, detail = "on", "One role has full access"
    features.append({
        "key": "access",
        "label": "Who can manage",
        "state": state,
        "detail": detail,
        "settings_key": "access",
    })

    return features
