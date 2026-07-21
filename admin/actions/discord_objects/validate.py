# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Validate Discord entities - existence/type + bot role-assignment capability."""

from __future__ import annotations

from typing import Optional

import discord


def validate_entity(guild: discord.Guild, entity_id: int, expected: str) -> tuple[bool, Optional[str]]:
    """Validate a Discord entity exists and matches ``expected`` type.

    ``expected``: "text_channel" | "voice_channel" | "category" | "role" | "member".
    Returns (True, None) or (False, error_message).
    """
    if expected == "role":
        return (True, None) if guild.get_role(entity_id) else (False, "Could not find that role.")
    if expected == "member":
        return (True, None) if guild.get_member(entity_id) else (False, "Could not find that member.")
    channel = guild.get_channel(entity_id)
    if channel is None:
        return False, "Could not find that channel."
    wanted = {
        "text_channel": discord.ChannelType.text,
        "voice_channel": discord.ChannelType.voice,
        "category": discord.ChannelType.category,
    }.get(expected)
    if wanted is not None and channel.type != wanted:
        return False, f"That channel is not a {expected.replace('_', ' ')}."
    return True, None


def validate_role_assignment(guild: discord.Guild, role_id: int, *, require_manageable: bool = True) -> tuple[bool, Optional[str]]:
    """Check the bot can assign/manage ``role_id`` (Manage Roles + hierarchy)."""
    role = guild.get_role(role_id)
    if role is None:
        return False, "Could not find that role."
    if not require_manageable:
        return True, None
    if not guild.me.guild_permissions.manage_roles:
        return False, "The bot is missing the **Manage Roles** permission."
    if role >= guild.me.top_role:
        return False, f"The bot's highest role must be **above** **@{role.name}** in the role hierarchy."
    return True, None
