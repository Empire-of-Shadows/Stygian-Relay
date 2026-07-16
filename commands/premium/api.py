"""Public premium API - the stable surface other cogs call.

Downstream code should use these, never the raw entitlement records. All reads go through the
attached `bot.premium_manager` (the storage master's PremiumManager), so this module stays a
thin, portable convenience + the `require_premium` command check.

    from commands.premium.api import is_premium, get_tier, require_premium

    @app_commands.command()
    @require_premium()
    async def fancy(self, interaction): ...
"""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands

from storage.bot_specific.relay.premium import SCOPE_GUILD, PremiumState


class PremiumRequired(app_commands.CheckFailure):
    """Raised by `require_premium` when a guild lacks the required premium tier."""

    def __init__(self, tier: Optional[str] = None):
        self.tier = tier
        super().__init__(
            f"This server needs the '{tier}' premium tier." if tier
            else "This server needs premium to use this."
        )


def _manager(bot):
    pm = getattr(bot, "premium_manager", None)
    if pm is None:
        raise RuntimeError("premium_manager is not attached to the bot")
    return pm


async def is_premium(bot, guild_id) -> bool:
    """True if the guild currently has any active premium."""
    return await _manager(bot).is_premium_guild(str(guild_id))


async def get_tier(bot, guild_id) -> Optional[str]:
    """The guild's best active tier label, or None if not premium."""
    return await _manager(bot).get_tier(SCOPE_GUILD, str(guild_id))


async def get_premium_state(bot, guild_id) -> PremiumState:
    """The full derived PremiumState for a guild (free-tier default when absent)."""
    return await _manager(bot).get_guild_state(str(guild_id))


def require_premium(*, tier: Optional[str] = None):
    """app_commands check: the invoking guild must be premium (optionally at a given tier)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            raise PremiumRequired(tier)
        pm = getattr(interaction.client, "premium_manager", None)
        if pm is None:
            raise PremiumRequired(tier)
        state = await pm.get_guild_state(str(interaction.guild_id))
        if not state.is_premium:
            raise PremiumRequired(tier)
        if tier and tier not in state.tiers:
            raise PremiumRequired(tier)
        return True

    return app_commands.check(predicate)
