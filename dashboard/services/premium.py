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


async def get_guild_limits(guild_id: str) -> dict:
    """Return rule and daily-message limits for the guild based on premium status."""
    settings_doc = await db.bot_settings().find_one({"_id": "global_config"})
    settings_doc = settings_doc or {}
    premium = await is_guild_premium(str(guild_id))
    # Fallbacks MUST match the bot-side enforcement layer
    # (storage_engine/bot_specific/relay/guild/guild_manager.py::get_guild_limits),
    # or the dashboard would promise a cap the bot doesn't honour.
    return {
        "max_rules": settings_doc.get(
            "max_rules_premium" if premium else "max_rules_per_guild", 20 if premium else 3
        ),
        "daily_limit": settings_doc.get(
            "premium_tier_daily_limit" if premium else "free_tier_daily_limit",
            5000 if premium else 100,
        ),
        "is_premium": premium,
    }
