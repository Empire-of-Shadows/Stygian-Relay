"""Stygian-Relay - admin engine bindings (the per-bot seam).

The vendored engine (``admin_cog.py``) is byte-identical across every bot; it reaches all of
Stygian-Relay's backends through the names defined here. See
``admin_engine/bindings_reference.py`` for the full contract.

All persistence flows through the bot's ``database`` package: per-guild settings via
``guild_manager`` (which owns the ``guild_settings`` collection + its cache) and audit entries
via ``audit_log``. The panel binds its leaves to inline ``guild_manager`` accessors in
``panel_configs.py``, so the generic ``config_*`` doers here are for engine-contract
completeness; Relay's panel has no collection-reset/delete actions, so the ``db_*`` doers are
inert stubs (the same pattern as TheHost).

Relay has no ``panel_branding.py``/``role_auth.py``; the static text and tier set the engine
reads are defined inline below (as in the reference template).
"""

from __future__ import annotations

from typing import Any

import discord

from storage.bot_specific.relay import guild_manager, audit_log

import logging

logger = logging.getLogger("AdminBindings")


# ── Static configuration the engine reads ───────────────────────────────────────

BOT_NAME = "Stygian-Relay"

# Relay gates the panel on Administrator or the configured manager role (see
# database/permissions.can_manage_guild_settings) - there is no mod tier.
MOD_ALLOWED_CATEGORIES: set[str] = set()

SETUP_GUIDE_TEXT = (
    "**Getting started with Stygian-Relay**\n"
    "Relay mirrors messages from one channel to another, in this server or "
    "across servers. Work through the sections below to go live:\n"
    "\n"
    "**1. Core** - Set a **Manager Role** so trusted members can change these "
    "settings without full admin, and a **Log Channel** where the bot posts "
    "activity and errors.\n"
    "**2. Feature Toggles** - Turn on **Message Forwarding** (the master "
    "switch; while it is off, no rules fire). Optionally enable **Error "
    "Notifications** for in-channel alerts, and use the **Inbound Forward "
    "Allowlist** to choose which other servers may forward messages into this "
    "one.\n"
    "**3. Forwarding Rules** - Add a rule for each source to destination pair "
    "you want mirrored. This section also shows your active rules and how many "
    "messages have been forwarded today.\n"
    "**4. Premium** - Check your subscription status and per-server limits "
    "(rules and daily forwards). Run `/premium status` for full details.\n"
    "\n"
    "You can hide this guide any time with the button below."
)
OVERVIEW_FOOTER = ""


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _dig(settings: dict, path: str, default: Any = None) -> Any:
    """Read a dotted ``path`` out of the flat guild-settings dict."""
    cur: Any = settings
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


# ── Tier resolution ──────────────────────────────────────────────────────────────

async def resolve_panel_role(user: discord.Member, guild_id: int) -> str:
    """Return "admin" | "none". Mirrors ``permissions.can_manage_guild_settings``:
    Administrator (or Manage Server) or the configured ``manager_role_id`` ⇒ admin."""
    perms = getattr(user, "guild_permissions", None)
    if perms is not None and (perms.administrator or perms.manage_guild):
        return "admin"
    settings = await guild_manager.get_guild_settings(str(guild_id))
    raw = settings.get("manager_role_id")
    if raw:
        try:
            mrid = int(raw)
        except (TypeError, ValueError):
            mrid = None
        if mrid and any(r.id == mrid for r in getattr(user, "roles", [])):
            return "admin"
    return "none"


# ── Dashboard flags (setup-guide toggle, etc.) ───────────────────────────────────

async def get_setting(key: str, guild_id: int, default: Any = None):
    return await config_get(guild_id, key, default)


async def set_setting(key: str, value: Any, guild_id: int) -> None:
    await config_set(guild_id, key, value)


# ── Premium ──────────────────────────────────────────────────────────────────────

async def is_premium(guild_id: int) -> bool:
    return bool(await guild_manager.is_premium_guild(str(guild_id)))


# ── Cache invalidation ───────────────────────────────────────────────────────────

def invalidate_caches(guild_id: int) -> None:
    """Drop this guild's cached settings + premium status (writes already invalidate the
    settings cache; this also covers out-of-band edits)."""
    try:
        guild_manager.settings_cache.invalidate(str(guild_id))
        guild_manager.premium_cache.invalidate(str(guild_id))
    except Exception as e:  # best-effort: never block a save
        logger.debug(f"invalidate_caches skipped for {guild_id}: {e}")


# ── Audit log ────────────────────────────────────────────────────────────────────

async def audit_log_entry(
    *,
    guild_id: int,
    actor_id: int,
    actor_name: str,
    section: str,
    key: str,
    old_value: object,
    new_value: object,
    action: str,
) -> None:
    """Record an admin-driven mutation via the bot's audit log
    (``log(category, guild_id, actor_id, action, payload)``)."""
    await audit_log.log(
        "settings",
        str(guild_id),
        str(actor_id),
        f"{action}:{section}.{key}",
        {
            "actor_name": actor_name,
            "section": section,
            "key": key,
            "old_value": old_value,
            "new_value": new_value,
        },
    )


# ── Config access (dotted-path over guild settings) ──────────────────────────────

async def config_get(guild_id: int, path: str, default=None):
    settings = await guild_manager.get_guild_settings(str(guild_id))
    return _dig(settings, path, default)


async def config_set(guild_id: int, path: str, value) -> bool:
    return await guild_manager.update_guild_settings(str(guild_id), {path: value})


async def config_unset(guild_id: int, path: str) -> bool:
    return await guild_manager.update_guild_settings(str(guild_id), {path: None})


# ── Collection access (inert - Relay's panel has no collection actions) ───────────

async def db_find(collection: str, query: dict, *, sort=None, limit: int | None = None) -> list[dict]:
    return []


async def db_count(collection: str, query: dict) -> int:
    return 0


async def db_delete_one(collection: str, query: dict) -> bool:
    return False


async def db_delete_many(collection: str, query: dict) -> int:
    return 0


async def db_update_one(collection: str, query: dict, update: dict, *, upsert: bool = False) -> bool:
    return False


async def db_insert_one(collection: str, doc: dict):
    return None
