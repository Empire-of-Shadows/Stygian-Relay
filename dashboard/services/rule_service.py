"""Forwarding rule CRUD against discord_forwarding_bot.guild_settings.rules[].

Standalone: does NOT import from the relay bot's storage package. Schema
migration is inlined here to keep the dashboard self-contained.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from dashboard import db
from dashboard.services.premium import get_guild_limits

RULE_SCHEMA_VERSION = 3

_DEFAULT_AUTHOR_FILTERS = {
    "allow_user_ids": [],
    "deny_user_ids": [],
    "allow_role_ids": [],
    "deny_role_ids": [],
}


def _migrate_rule(rule: dict) -> dict:
    if rule.get("schema_version") == RULE_SCHEMA_VERSION:
        return rule
    settings = rule.setdefault("settings", {})
    if "author_filters" not in settings:
        settings["author_filters"] = dict(_DEFAULT_AUTHOR_FILTERS)
    rule["schema_version"] = RULE_SCHEMA_VERSION
    return rule


def _migrate_rules(rules: list[dict]) -> list[dict]:
    return [_migrate_rule(r) for r in rules]


def _serialize_rule(rule: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in rule.items():
        if k == "_id":
            continue
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


async def get_rules(guild_id: str) -> list[dict]:
    """Return all rules for a guild, migrated to the current schema version."""
    doc = await db.guild_settings().find_one(
        {"guild_id": str(guild_id)}, {"rules": 1}
    )
    if not doc:
        return []
    rules = doc.get("rules") or []
    return [_serialize_rule(_migrate_rule(r)) for r in rules]


async def get_rule(guild_id: str, rule_id: str) -> dict | None:
    """Return a single rule, or None if not found."""
    doc = await db.guild_settings().find_one(
        {"guild_id": str(guild_id), "rules.rule_id": rule_id},
        {"rules.$": 1},
    )
    if not doc or not doc.get("rules"):
        return None
    return _serialize_rule(_migrate_rule(doc["rules"][0]))


async def create_rule(
    guild_id: str,
    *,
    rule_name: str,
    source_channel_id: int,
    destination_channel_id: int,
    destination_guild_id: int | None = None,
    author_filters: dict | None = None,
    is_active: bool = True,
) -> tuple[bool, str, dict | None]:
    """Add a rule, enforcing the per-guild cap. Returns (success, reason, rule)."""
    gid = str(guild_id)
    limits = await get_guild_limits(gid)
    max_rules = int(limits["max_rules"])

    dest_guild = destination_guild_id if destination_guild_id is not None else int(guild_id)
    filters = author_filters if author_filters else dict(_DEFAULT_AUTHOR_FILTERS)

    now = datetime.now(timezone.utc)
    rule_data: dict = {
        "rule_id": str(uuid.uuid4()),
        "rule_name": rule_name,
        "source_channel_id": source_channel_id,
        "destination_channel_id": destination_channel_id,
        "destination_guild_id": dest_guild,
        "is_active": is_active,
        "settings": {"author_filters": filters},
        "schema_version": RULE_SCHEMA_VERSION,
        "created_at": now,
        "updated_at": now,
    }

    active_filter = {
        "$expr": {
            "$lt": [
                {"$size": {
                    "$filter": {
                        "input": {"$ifNull": ["$rules", []]},
                        "as": "r",
                        "cond": {"$eq": ["$$r.is_active", True]},
                    }
                }},
                max_rules,
            ]
        }
    }

    coll = db.guild_settings()
    result = await coll.update_one(
        {"guild_id": gid, **active_filter},
        {
            "$push": {"rules": rule_data},
            "$set": {"updated_at": now},
        },
    )

    if result.modified_count > 0:
        return True, "ok", _serialize_rule(rule_data)

    # Disambiguate: limit reached vs guild not found.
    existing = await coll.find_one({"guild_id": gid}, {"rules": 1})
    if existing is None:
        return False, "guild_not_found", None
    active_count = sum(1 for r in (existing.get("rules") or []) if r.get("is_active"))
    if active_count >= max_rules:
        return False, "limit_reached", None
    return False, "error", None


async def update_rule(guild_id: str, rule_id: str, updates: dict) -> bool:
    """Update fields of a specific rule. Returns True if modified."""
    now = datetime.now(timezone.utc)
    set_fields = {f"rules.$.{k}": v for k, v in updates.items()}
    set_fields["rules.$.updated_at"] = now

    result = await db.guild_settings().update_one(
        {"guild_id": str(guild_id), "rules.rule_id": rule_id},
        {"$set": set_fields},
    )
    return result.modified_count > 0


async def delete_rule(guild_id: str, rule_id: str) -> bool:
    """Permanently remove a rule from the array. Returns True if removed."""
    result = await db.guild_settings().update_one(
        {"guild_id": str(guild_id)},
        {"$pull": {"rules": {"rule_id": rule_id}}},
    )
    return result.modified_count > 0


async def toggle_rule(guild_id: str, rule_id: str) -> bool | None:
    """Toggle is_active for a rule. Returns new state or None if not found."""
    rule = await get_rule(guild_id, rule_id)
    if rule is None:
        return None
    new_active = not rule.get("is_active", True)
    ok = await update_rule(guild_id, rule_id, {"is_active": new_active})
    return new_active if ok else None
