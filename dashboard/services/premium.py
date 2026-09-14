"""Premium status helpers for the Relay dashboard (entitlement-backed, read-only).

Reads the derived ``premium_state`` doc that the bot's PremiumManager maintains from
entitlements. The dashboard never writes premium - grants happen in Discord (real entitlements)
or via the bot's owner `/premium grant` command.
"""

from __future__ import annotations

from datetime import datetime, timezone

from dashboard import db


def _ensure_utc(dt):
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_premium_status(guild_id: str) -> dict:
    """Return the derived premium status for a guild from the ``premium_state`` doc."""
    doc = await db.premium_state().find_one({"_id": f"guild:{str(guild_id)}"})
    if not doc or not doc.get("is_premium"):
        return {"is_premium": False, "tier": "free", "tiers": [], "expires_at": None}

    expires_at = _ensure_utc(doc.get("expires_at"))
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        # Lapsed since the bot last recomputed; the next reconcile flips the stored doc.
        return {"is_premium": False, "tier": "free", "tiers": [], "expires_at": None}

    tiers = doc.get("tiers") or []
    return {
        "is_premium": True,
        "tier": doc.get("tier") or (tiers[0] if tiers else "premium"),
        "tiers": tiers,
        "expires_at": expires_at,
    }


async def is_guild_premium(guild_id: str) -> bool:
    """True if the guild has active premium."""
    return (await get_premium_status(str(guild_id)))["is_premium"]


#: The defaults the bot writes into ``bot_settings.global_config`` and falls back to when a
#: key is missing (storage_engine/bot_specific/relay/guild/constants.py::DEFAULT_BOT_SETTINGS).
#: They MUST match it, or the dashboard would promise a cap the bot does not enforce.
DEFAULT_LIMITS = {
    "max_rules_per_guild": 15,
    "free_tier_daily_limit": 500,
    "max_rules_premium": 40,
    "premium_tier_daily_limit": 5000,
}


def _limits_for(settings_doc: dict, premium: bool) -> dict:
    rules_key = "max_rules_premium" if premium else "max_rules_per_guild"
    daily_key = "premium_tier_daily_limit" if premium else "free_tier_daily_limit"
    return {
        "max_rules": int(settings_doc.get(rules_key, DEFAULT_LIMITS[rules_key])),
        "daily_limit": int(settings_doc.get(daily_key, DEFAULT_LIMITS[daily_key])),
    }


async def plan_limits() -> dict:
    """Both plans' limits as the bot enforces them right now, for the side-by-side tables."""
    settings_doc = await db.bot_settings().find_one({"_id": "global_config"}) or {}
    return {"free": _limits_for(settings_doc, False), "premium": _limits_for(settings_doc, True)}


async def get_guild_limits(guild_id: str) -> dict:
    """Return rule and daily-message limits for the guild based on premium status."""
    settings_doc = await db.bot_settings().find_one({"_id": "global_config"}) or {}
    premium = await is_guild_premium(str(guild_id))
    return {**_limits_for(settings_doc, premium), "is_premium": premium}
