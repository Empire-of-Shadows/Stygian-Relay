"""Per-guild forwarding analytics API.

All forwarded-message analytics derive from ``message_logs`` (per-message,
90-day TTL) rather than ``daily_counters`` (which only keeps a ~3-day quota
counter). Blocked/denied analytics come from ``denial_counters``, the
per-(guild, day, reason) buckets the bot writes when it rate-limits, hits a
daily cap, or skips a misconfigured rule.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from dashboard import db
from dashboard.auth.dependencies import get_current_user, require_panel_access
from dashboard.services.premium import get_guild_limits

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stats"])


def _date_range(start: datetime, end: datetime) -> list[str]:
    """Inclusive list of ``YYYY-MM-DD`` strings from ``start`` to ``end`` (UTC)."""
    out: list[str] = []
    day = start.date()
    last = end.date()
    while day <= last:
        out.append(day.isoformat())
        day += timedelta(days=1)
    return out


@router.get("/guilds/{guild_id}/stats")
async def guild_stats(
    guild_id: str,
    days: int = Query(default=30, ge=1, le=90),
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)

    gid = str(guild_id)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    cutoff_date = cutoff.date().isoformat()

    limits = await get_guild_limits(gid)

    # ── One pass over message_logs: every forwarded-side metric as a facet ──
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
                "hourly": [
                    {
                        "$group": {
                            "_id": {"$hour": {"date": "$forwarded_at", "timezone": "UTC"}},
                            "count": {"$sum": 1},
                        }
                    },
                ],
                "per_rule": [
                    {"$group": {"_id": "$rule_id", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 25},
                ],
                "per_source": [
                    {"$group": {"_id": "$source_channel_id", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 10},
                ],
                "total": [{"$count": "n"}],
                # Distinct source messages, counted by grouping first so we never
                # build a giant $addToSet array in a single document.
                "unique_sources": [
                    {"$group": {"_id": "$original_message_id"}},
                    {"$count": "n"},
                ],
            }
        },
    ]

    cursor = await db.message_logs().aggregate(facet_pipeline)
    facet_docs = await cursor.to_list(length=1)
    facet = facet_docs[0] if facet_docs else {}

    def _first_n(rows: list[dict]) -> int:
        return int(rows[0]["n"]) if rows else 0

    total_forwarded = _first_n(facet.get("total", []))
    unique_sources = _first_n(facet.get("unique_sources", []))

    daily_forwarded = {row["_id"]: int(row["count"]) for row in facet.get("daily", [])}

    hourly_map = {int(row["_id"]): int(row["count"]) for row in facet.get("hourly", [])}
    hourly = [hourly_map.get(h, 0) for h in range(24)]

    # ── Blocked/denied series from denial_counters ─────────────────────────
    daily_blocked: dict[str, int] = {}
    blocked_by_reason: dict[str, int] = {}
    total_blocked = 0
    denial_cursor = db.denial_counters().find(
        {"guild_id": gid, "date": {"$gte": cutoff_date}},
        {"_id": 0, "date": 1, "reason": 1, "count": 1},
    )
    async for doc in denial_cursor:
        c = int(doc.get("count", 0))
        date = doc.get("date")
        reason = doc.get("reason") or "unknown"
        total_blocked += c
        if date:
            daily_blocked[date] = daily_blocked.get(date, 0) + c
        blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + c

    # ── Gap-filled daily series (forwarded + blocked share the same days) ──
    daily = [
        {
            "date": d,
            "forwarded": daily_forwarded.get(d, 0),
            "blocked": daily_blocked.get(d, 0),
        }
        for d in _date_range(cutoff, now)
    ]

    today_str = now.strftime("%Y-%m-%d")
    today_forwarded = daily_forwarded.get(today_str, 0)

    peak = max(daily, key=lambda d: d["forwarded"], default=None)
    peak_out = (
        {"date": peak["date"], "forwarded": peak["forwarded"]}
        if peak and peak["forwarded"] > 0
        else None
    )
    daily_average = round(total_forwarded / days, 1) if days else 0.0
    fanout_ratio = round(total_forwarded / unique_sources, 2) if unique_sources else 0.0

    # ── Enrich rules with names + channels from the guild config ───────────
    settings_doc = await db.guild_settings().find_one({"guild_id": gid}, {"rules": 1})
    rules = (settings_doc or {}).get("rules") or []
    rule_map = {r.get("rule_id"): r for r in rules}
    active_rules = sum(1 for r in rules if r.get("is_active"))

    per_rule = []
    for row in facet.get("per_rule", []):
        rid = row["_id"]
        r = rule_map.get(rid)
        if r is not None:
            per_rule.append({
                "rule_id": rid,
                "rule_name": r.get("rule_name") or "Unnamed rule",
                "source_channel_id": str(r.get("source_channel_id") or ""),
                "destination_channel_id": str(r.get("destination_channel_id") or ""),
                "destination_guild_id": str(r.get("destination_guild_id") or ""),
                "is_active": bool(r.get("is_active")),
                "deleted": False,
                "forwarded": int(row["count"]),
            })
        else:
            # Rule was deleted since these messages were forwarded.
            per_rule.append({
                "rule_id": rid,
                "rule_name": "Deleted rule",
                "source_channel_id": "",
                "destination_channel_id": "",
                "destination_guild_id": "",
                "is_active": False,
                "deleted": True,
                "forwarded": int(row["count"]),
            })

    per_source = [
        {"channel_id": str(row["_id"] or ""), "forwarded": int(row["count"])}
        for row in facet.get("per_source", [])
    ]

    blocked_reasons = sorted(
        ({"reason": k, "count": v} for k, v in blocked_by_reason.items()),
        key=lambda x: x["count"],
        reverse=True,
    )

    return {
        "guild_id": gid,
        "period_days": days,
        "generated_at": now.isoformat(),
        "daily_limit": limits["daily_limit"],
        "is_premium": limits["is_premium"],
        "totals": {
            "forwarded": total_forwarded,
            "blocked": total_blocked,
            "today_forwarded": today_forwarded,
            "daily_average": daily_average,
            "unique_sources": unique_sources,
            "fanout_ratio": fanout_ratio,
            "active_rules": active_rules,
            "peak": peak_out,
        },
        "daily": daily,
        "hourly": hourly,
        "per_rule": per_rule,
        "per_source": per_source,
        "blocked_by_reason": blocked_reasons,
    }
