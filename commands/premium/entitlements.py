"""Normalize a discord.py `Entitlement` into the storage record dict.

This is the one place that touches discord.py's Entitlement shape, so the discord-free storage
master (`PremiumManager`) only ever sees plain dicts. Tier resolution comes from the per-bot
SKU map in the settings seam - an entitlement whose SKU is not configured is stored as the
"unknown" tier and warned about, never dropped.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import discord

from storage.bot_specific.relay.premium import SCOPE_GUILD, SCOPE_USER, TIER_UNKNOWN

from .settings import PremiumSettings

logger = logging.getLogger("PremiumEntitlements")


def normalize(entitlement: discord.Entitlement, settings: PremiumSettings) -> Dict[str, Any]:
    """Convert a discord.Entitlement to the canonical storage dict (scope resolved, tier mapped)."""
    guild_id = getattr(entitlement, "guild_id", None)
    user_id = getattr(entitlement, "user_id", None)
    sku_id = str(entitlement.sku_id)

    tier = settings.tier_for_sku(sku_id)
    if tier == TIER_UNKNOWN and sku_id not in settings.skus:
        logger.warning(
            "Entitlement %s references unconfigured SKU %s - stored as tier 'unknown'. "
            "Add it to the settings SKUS map.", entitlement.id, sku_id,
        )

    if guild_id:
        scope, scope_id = SCOPE_GUILD, str(guild_id)
    else:
        scope, scope_id = SCOPE_USER, str(user_id)

    ent_type = getattr(entitlement, "type", None)
    type_value = getattr(ent_type, "value", ent_type)

    return {
        "entitlement_id": str(entitlement.id),
        "sku_id": sku_id,
        "application_id": str(entitlement.application_id) if getattr(entitlement, "application_id", None) else None,
        "scope": scope,
        "scope_id": scope_id,
        "guild_id": str(guild_id) if guild_id else None,
        "user_id": str(user_id) if user_id else None,
        "type": type_value,
        "tier": tier,
        "deleted": bool(getattr(entitlement, "deleted", False)),
        "starts_at": getattr(entitlement, "starts_at", None),
        "ends_at": getattr(entitlement, "ends_at", None),
        "consumed": bool(getattr(entitlement, "consumed", False)),
    }
