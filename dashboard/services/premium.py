"""Premium status helpers for the Relay dashboard."""

from __future__ import annotations

from datetime import datetime, timezone

from dashboard import db


async def get_premium_subscription(guild_id: str) -> dict | None:
    """Return the active premium subscription doc, or None."""
    now = datetime.now(timezone.utc)
    sub = await db.premium_subscriptions().find_one({
        "guild_id": str(guild_id),
        "is_active": True,
        "is_lifetime": True,
    })
    if sub:
        return sub
    sub = await db.premium_subscriptions().find_one({
        "guild_id": str(guild_id),
        "is_active": True,
        "expires_at": {"$gt": now},
    })
    return sub


async def is_guild_premium(guild_id: str) -> bool:
    """True if the guild has an active subscription."""
    return await get_premium_subscription(str(guild_id)) is not None


async def get_guild_limits(guild_id: str) -> dict:
    """Return rule and daily-message limits for the guild based on premium tier."""
    settings_doc = await db.bot_settings().find_one({"_id": "global_config"})
    settings_doc = settings_doc or {}
    premium = await is_guild_premium(str(guild_id))
    return {
        "max_rules": settings_doc.get(
            "max_rules_premium" if premium else "max_rules_per_guild", 40 if premium else 15
        ),
        "daily_limit": settings_doc.get(
            "premium_tier_daily_limit" if premium else "free_tier_daily_limit",
            5000 if premium else 500,
        ),
        "is_premium": premium,
    }
