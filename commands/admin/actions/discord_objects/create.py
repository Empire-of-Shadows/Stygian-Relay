# ───────────────────────────────────────────────────────────────────────────
# VENDORED from admin_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Create Discord entities (role / channel) — thin, reusable wrappers."""

from __future__ import annotations

import logging
from typing import Optional

import discord

logger = logging.getLogger("AdminActions.discord")


async def create_role(guild: discord.Guild, name: str, *, reason: str = "Admin panel", **kwargs) -> Optional[discord.Role]:
    """Create a guild role; returns it (or None on failure)."""
    try:
        return await guild.create_role(name=name, reason=reason, **kwargs)
    except discord.HTTPException as exc:
        logger.warning("create_role failed for %r: %s", name, exc)
        return None


async def create_channel(guild: discord.Guild, name: str, *, kind: str = "text",
                         reason: str = "Admin panel", **kwargs):
    """Create a guild channel (``kind`` = "text" | "voice" | "category"); returns it or None."""
    factory = {
        "text": guild.create_text_channel,
        "voice": guild.create_voice_channel,
        "category": guild.create_category,
    }.get(kind, guild.create_text_channel)
    try:
        return await factory(name=name, reason=reason, **kwargs)
    except discord.HTTPException as exc:
        logger.warning("create_channel failed for %r: %s", name, exc)
        return None


# -- Create-and-store action factories ----------------------------------------
# Thin wrappers over modal_action: open a modal for a name, create the entity, then
# persist its id to a config path. Generalizes Ecom's "Create Active Role" flow.

def create_role_action(
    key, *, label, store_path, name_label="Role name", description="",
    reason="Admin panel", mod_allowed=False, premium_label=None, **role_kwargs,
):
    """An ``action`` node: prompt for a role name, create the role, store its id at
    config ``store_path``. Extra kwargs pass through to ``guild.create_role``."""
    from ..structure.modals import modal_action
    from ..config.fields import set_config_field

    async def _submit(guild, raw):
        role = await create_role(guild, raw, reason=reason, **role_kwargs)
        if role is None:
            raise RuntimeError("role creation failed")
        await set_config_field(guild.id, store_path, role.id)
        return role

    return modal_action(
        key, label=label, description=description, field_label=name_label,
        on_submit=_submit, success_text=lambda r: f"Created and saved {r.mention}.",
        mod_allowed=mod_allowed, premium_label=premium_label,
    )


def create_channel_action(
    key, *, label, store_path, kind="text", name_label="Channel name", description="",
    reason="Admin panel", mod_allowed=False, premium_label=None, **channel_kwargs,
):
    """An ``action`` node: prompt for a channel name, create the channel (``kind`` =
    "text" | "voice" | "category"), store its id at config ``store_path``."""
    from ..structure.modals import modal_action
    from ..config.fields import set_config_field

    async def _submit(guild, raw):
        channel = await create_channel(guild, raw, kind=kind, reason=reason, **channel_kwargs)
        if channel is None:
            raise RuntimeError("channel creation failed")
        await set_config_field(guild.id, store_path, channel.id)
        return channel

    return modal_action(
        key, label=label, description=description, field_label=name_label,
        on_submit=_submit, success_text=lambda c: f"Created and saved {c.mention}.",
        mod_allowed=mod_allowed, premium_label=premium_label,
    )
