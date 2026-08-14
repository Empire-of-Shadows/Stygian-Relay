"""User-scoped data for the privacy page: the two choices, the export, and the erasure.

Relay stores almost nothing about an individual member, and that is the honest headline
of this whole module. It is a message forwarder: it reads a message, reposts it, and
writes a delivery record that names the rule and the channels but NOT the author. So the
three places a member's own id can appear are:

  ``user_preferences``  their two privacy choices - written only here.
  ``audit_logs``        ``actor_id`` on an admin action they took, if they are an admin.
  ``guild_settings``    their id inside a rule's ``settings.author_filters`` lists, where
                        a server admin has singled them out to be always- or never-
                        relayed.
  ``entitlements``      ``user_id`` on a premium purchase they made.

``message_logs`` is deliberately absent and that is NOT an oversight: it carries
``original_message_id`` and channel ids but no author, so there is no way to look a
member up in it and nothing of theirs to return or delete. Do not "improve" that by
joining through Discord.

WHAT DELETE DOES, per owner ruling 2026-08-13 (full erasure):

  Removed  - their id is ``$pull``ed out of every rule's four author-filter lists, in
             every server in scope. This CHANGES WHAT GETS RELAYED: a deny entry that was
             keeping their messages out is gone, and an allow entry that was the only
             thing letting them through is gone too. The page says so before the member
             confirms.
  Kept     - audit entries, because a server keeps a complete record of who changed what.
  Kept     - their privacy choices, because an erasure must never switch relaying back on.
  Kept     - entitlements, because they are a purchase record.
  Impossible - copies already posted into a Discord channel. Relay does not own those
             messages and cannot delete them. Said plainly on the page rather than
             quietly left out of the count.

Every stored id in this database is a STRING. Querying with an int matches nothing,
silently.
"""

from __future__ import annotations

import time

from dashboard import db

#: The privacy toggles, in the order the page shows them. ``all`` is the master switch;
#: a ``True`` value means the member has OPTED OUT of that thing. Mirrors the bot-side
#: ``storage/settings/user_preferences.py`` - the two must move together.
PRIVACY_FEATURES: tuple[str, ...] = ("all", "relay_messages", "show_name")

#: A rule's author filters have four lists - allow/deny users and allow/deny roles - but
#: only the two USER lists can ever hold a member's own id; the role lists hold role ids.
#: Export and delete therefore look at exactly these two.
AUTHOR_USER_KEYS: tuple[str, ...] = ("allow_user_ids", "deny_user_ids")


def _strip(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "_id"}


def _default_features() -> dict[str, bool]:
    """Every toggle off - what a member with no stored document has."""
    return {name: False for name in PRIVACY_FEATURES}


def _normalize_features(stored: dict | None) -> dict[str, bool]:
    """Coerce a stored features map to exactly the known booleans."""
    stored = stored or {}
    return {name: bool(stored.get(name, False)) for name in PRIVACY_FEATURES}


def _named_in_rule(rule: dict, uid: str) -> list[str]:
    """Which author-filter lists of one rule name this member. Empty when none do."""
    filters = (rule.get("settings") or {}).get("author_filters") or {}
    hits: list[str] = []
    for key in AUTHOR_USER_KEYS:
        values = filters.get(key) or []
        if any(str(v) == uid for v in values):
            hits.append(key)
    return hits


# ── Privacy preferences ──────────────────────────────────────────────────────


async def get_privacy(user_id: str) -> dict[str, bool]:
    """The member's privacy choices. No stored document means every toggle is off."""
    doc = await db.user_preferences().find_one({"user_id": str(user_id)})
    if not doc:
        return _default_features()
    return _normalize_features(doc.get("features"))


async def set_privacy(user_id: str, features: dict[str, bool]) -> dict[str, bool]:
    """Upsert the member's choices and return what was saved.

    ``created_at`` is stamped on insert only, ``updated_at`` on every write, both as
    integer Unix seconds (the ecosystem convention). Forward-only: this never touches
    anything already stored, and never reaches into Discord.

    The bot serves these from a 60-second cache, which is why the page promises the
    change takes effect "within about a minute" rather than instantly.
    """
    clean = _normalize_features(features)
    now = int(time.time())
    await db.user_preferences().update_one(
        {"user_id": str(user_id)},
        {
            "$set": {"features": clean, "updated_at": now},
            "$setOnInsert": {"user_id": str(user_id), "created_at": now},
        },
        upsert=True,
    )
    return clean


async def count_relay_opt_outs() -> int:
    """How many accounts have asked relay not to relay their messages.

    A COUNT, never names - owner ruling 2026-08-13. It exists so an admin looking at a
    mirror with gaps in it has an explanation other than "the bot is broken".

    It is deliberately NOT scoped to one server, and the page must say so. A relay opt-out
    is account-wide, and ``user_preferences`` holds no guild dimension to filter on;
    narrowing it to one server would mean pulling that server's whole member list from
    Discord on every page load to intersect against. Reporting a global figure as if it
    were "members of this server" would be the dishonest option, so the page states what
    the number actually counts.
    """
    return await db.user_preferences().count_documents(
        {"$or": [{"features.all": True}, {"features.relay_messages": True}]}
    )


# ── Scope ────────────────────────────────────────────────────────────────────


async def distinct_guild_ids(user_id: str) -> set[str]:
    """Guild ids (as strings) where relay holds something of this member's.

    Drives the privacy page's scope picker, so it has to cover every guild-scoped thing
    the export and delete below reach: audit entries where they acted, and rules that
    name them. Their privacy choices and their entitlements are account-wide and
    contribute no guild of their own.
    """
    uid = str(user_id)
    ids: set[str] = set()

    async for doc in db.audit_logs().find({"actor_id": uid}, {"guild_id": 1}):
        if doc.get("guild_id") is not None:
            ids.add(str(doc["guild_id"]))

    # A rule names the member inside a nested array of arrays, which no index shape can
    # answer cheaply, so this reads the guilds that have rules at all and filters in
    # Python. Relay's guild count is small (tens), and the alternative is a $elemMatch
    # over four sibling arrays per rule.
    async for doc in db.guild_settings().find(
        {"rules": {"$exists": True, "$ne": []}}, {"guild_id": 1, "rules": 1}
    ):
        for rule in doc.get("rules") or []:
            if _named_in_rule(rule, uid):
                ids.add(str(doc.get("guild_id")))
                break

    return ids


# ── Export ───────────────────────────────────────────────────────────────────


async def export_all(user_id: str, guild_id: str | None = None) -> dict:
    """Everything relay holds for one member, optionally scoped to one server.

    Small by design - see the module docstring for why, and for what deliberately is not
    in here. The payload carries a ``notes`` block saying that in the file itself, so a
    member reading the download outside the dashboard is not left wondering whether the
    export is thin or broken.
    """
    uid = str(user_id)
    gid = str(guild_id) if guild_id is not None else None

    audit_match: dict = {"actor_id": uid}
    if gid is not None:
        audit_match["guild_id"] = gid
    audit_entries = [_strip(doc) async for doc in db.audit_logs().find(audit_match)]

    settings_match: dict = {"rules": {"$exists": True, "$ne": []}}
    if gid is not None:
        settings_match["guild_id"] = gid
    rule_mentions: list[dict] = []
    async for doc in db.guild_settings().find(
        settings_match, {"guild_id": 1, "rules": 1}
    ):
        for rule in doc.get("rules") or []:
            hits = _named_in_rule(rule, uid)
            if not hits:
                continue
            rule_mentions.append({
                "guild_id": str(doc.get("guild_id") or ""),
                "rule_id": str(rule.get("rule_id") or ""),
                "rule_name": rule.get("rule_name") or "",
                "is_active": bool(rule.get("is_active")),
                "source_channel_id": str(rule.get("source_channel_id") or ""),
                "destination_channel_id": str(rule.get("destination_channel_id") or ""),
                "listed_in": hits,
            })

    # Entitlements are account-wide (a purchase, not a server's data), so they are always
    # included even on a scoped export.
    entitlements = [_strip(doc) async for doc in db.entitlements().find({"user_id": uid})]

    privacy_doc = await db.user_preferences().find_one({"user_id": uid})
    privacy_preferences = {
        "features": _normalize_features((privacy_doc or {}).get("features")),
        "created_at": (privacy_doc or {}).get("created_at"),
        "updated_at": (privacy_doc or {}).get("updated_at"),
        "stored": privacy_doc is not None,
    }

    return {
        "user_id": uid,
        "guild_id": gid,
        "privacy_preferences": privacy_preferences,
        "audit_log_entries": audit_entries,
        "rules_naming_you": rule_mentions,
        "premium_entitlements": entitlements,
        "notes": [
            "This file is small because Stygian Relay stores almost nothing about you.",
            "It forwards messages; it does not keep the messages it forwards.",
            "The delivery record it writes for each forwarded message names the rule and "
            "the channels, not the author, so there is nothing of yours in it to export.",
            "Copies already posted into a Discord channel belong to that channel and are "
            "not included here.",
        ],
    }


# ── Delete ───────────────────────────────────────────────────────────────────


async def delete_all(user_id: str, guild_id: str | None = None) -> dict[str, int]:
    """Full erasure of the member's id from relay's rules, optionally in one server.

    Owner ruling 2026-08-13: this is a FULL erasure, so their id comes out of every
    rule's author-filter lists rather than being left in place. That changes what the
    server relays - the page states it before the member confirms.

    Returns per-item counts. ``rules_unnamed`` counts rules whose filters were edited,
    not rules deleted; no rule is ever deleted by a member's erasure request.
    """
    uid = str(user_id)
    gid = str(guild_id) if guild_id is not None else None

    settings_match: dict = {"rules": {"$exists": True, "$ne": []}}
    if gid is not None:
        settings_match["guild_id"] = gid

    rules_unnamed = 0
    async for doc in db.guild_settings().find(
        settings_match, {"guild_id": 1, "rules": 1}
    ):
        rules = doc.get("rules") or []
        for index, rule in enumerate(rules):
            hits = _named_in_rule(rule, uid)
            if not hits:
                continue
            filters = dict((rule.get("settings") or {}).get("author_filters") or {})
            for key in hits:
                filters[key] = [v for v in (filters.get(key) or []) if str(v) != uid]
            # A dotted positional write cannot address "the Nth element" of an array, so
            # the index is written explicitly. Matched on the rule_id as well as the
            # index so a concurrent rule edit cannot make this land on a different rule.
            result = await db.guild_settings().update_one(
                {
                    "guild_id": str(doc.get("guild_id")),
                    f"rules.{index}.rule_id": rule.get("rule_id"),
                },
                {"$set": {f"rules.{index}.settings.author_filters": filters}},
            )
            if result.modified_count > 0:
                rules_unnamed += 1

    return {"rules_unnamed": rules_unnamed}
