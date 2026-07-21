# VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
# Edit the master at EmpireSystems/dashboard_engine/ and run:
#     python EmpireSystems/tools/sync_dashboard_engine.py
# Drift is enforced by:
#     python EmpireSystems/tools/sync_dashboard_engine.py --check
"""Shared panel-access plumbing: live Discord permission/role checks.

Bot-agnostic machinery each dashboard's ``auth/panel_role.py`` seam builds its own tier
policy on top of. Provides the LIVE guild-permission check (``has_manage_guild`` via the bot
token, computing ADMINISTRATOR / MANAGE_GUILD from role permissions), the member-role fetch
(``member_role_ids``), a session-snapshot hint (``session_has_manage_guild``), plus the
internal token-bucket rate limiter and TTL caches that keep the bot-token fetches within
Discord's limits. Only the seam's tier model (2-tier vs 3-tier, role data source) is per-bot.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

import httpx

from dashboard.config import (
    ADMINISTRATOR_PERMISSION,
    BOT_TOKEN,
    DISCORD_API_BASE,
    MANAGE_GUILD_PERMISSION,
)

logger = logging.getLogger("dashboard.auth.panel_access")

PanelRole = Literal["admin", "mod", "none"]

_MEMBER_CACHE_TTL = 60.0
_MEMBER_NEGATIVE_TTL = 60.0

_member_cache: dict[tuple[str, str], tuple[frozenset[str], float]] = {}
_cache_lock = asyncio.Lock()

_guild_perm_cache: dict[str, tuple[tuple[str, dict[str, int]] | None, float]] = {}
_GUILD_PERM_TTL = 60.0

# Token bucket for the bot-token fetch path. Discord's global bot limit is 50/s; stay well
# under to leave headroom for the channels/roles/guilds fetches sharing the token. Both
# /api/me and /api/guilds probe panel roles, so a user in many configured guilds could
# otherwise burst member fetches.
_RATE_CAPACITY = 5
_RATE_REFILL_PER_SEC = 20.0
_rate_tokens = float(_RATE_CAPACITY)
_rate_last_refill = time.monotonic()
_rate_lock = asyncio.Lock()


def session_has_manage_guild(session: dict, guild_id: str) -> bool:
    """Cheap MANAGE_GUILD check from the OAuth login snapshot (display hint only)."""
    for g in session.get("guilds", []):
        if str(g["id"]) == str(guild_id):
            perms = int(g.get("permissions", 0))
            return (perms & MANAGE_GUILD_PERMISSION) == MANAGE_GUILD_PERMISSION
    return False


async def _acquire_rate_slot() -> None:
    """Block until the internal token bucket releases a slot."""
    global _rate_tokens, _rate_last_refill
    while True:
        async with _rate_lock:
            now = time.monotonic()
            elapsed = now - _rate_last_refill
            if elapsed > 0:
                _rate_tokens = min(
                    float(_RATE_CAPACITY),
                    _rate_tokens + elapsed * _RATE_REFILL_PER_SEC,
                )
                _rate_last_refill = now
            if _rate_tokens >= 1.0:
                _rate_tokens -= 1.0
                return
            need = 1.0 - _rate_tokens
            wait = need / _RATE_REFILL_PER_SEC
        await asyncio.sleep(wait)


async def member_role_ids(guild_id: str, user_id: str) -> frozenset[str]:
    """Live (cached) fetch of a member's role ids via the bot token."""
    key = (str(guild_id), str(user_id))
    now = time.monotonic()
    cached = _member_cache.get(key)
    if cached is not None and now - cached[1] < _MEMBER_CACHE_TTL:
        return cached[0]

    if not BOT_TOKEN:
        return frozenset()

    await _acquire_rate_slot()

    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 429:
                retry = float(resp.headers.get("Retry-After", "2"))
                await asyncio.sleep(retry)
                await _acquire_rate_slot()
                resp = await client.get(url, headers=headers)
    except Exception as e:
        logger.warning("Discord member fetch failed for %s/%s: %s", guild_id, user_id, e)
        return frozenset()

    if resp.status_code == 404:
        # User not a member - cache the empty result for the full TTL.
        roles: frozenset[str] = frozenset()
    elif resp.status_code == 200:
        roles = frozenset(str(r) for r in resp.json().get("roles", []))
    else:
        logger.warning("Discord member fetch %s/%s -> %s", guild_id, user_id, resp.status_code)
        # Cache unexpected failures for the shorter negative TTL so they clear quickly.
        async with _cache_lock:
            _member_cache[key] = (frozenset(), now - (_MEMBER_CACHE_TTL - _MEMBER_NEGATIVE_TTL))
        return frozenset()

    async with _cache_lock:
        _member_cache[key] = (roles, now)
    return roles


async def _guild_perm_context(guild_id: str) -> tuple[str, dict[str, int]] | None:
    """Live (cached) (owner_id, {role_id: permissions}) for a guild via the bot token."""
    key = str(guild_id)
    now = time.monotonic()
    cached = _guild_perm_cache.get(key)
    if cached is not None and now - cached[1] < _GUILD_PERM_TTL:
        return cached[0]

    if not BOT_TOKEN:
        return None

    await _acquire_rate_slot()

    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 429:
                retry = float(resp.headers.get("Retry-After", "2"))
                await asyncio.sleep(retry)
                await _acquire_rate_slot()
                resp = await client.get(url, headers=headers)
    except Exception as e:
        logger.warning("Discord guild fetch failed for %s: %s", guild_id, e)
        return None

    if resp.status_code != 200:
        logger.debug("Discord guild fetch %s -> %s", guild_id, resp.status_code)
        async with _cache_lock:
            _guild_perm_cache[key] = (None, now)
        return None

    data = resp.json()
    owner_id = str(data.get("owner_id", ""))
    role_perms = {
        str(r["id"]): int(r.get("permissions", 0))
        for r in data.get("roles", [])
    }
    ctx = (owner_id, role_perms)
    async with _cache_lock:
        _guild_perm_cache[key] = (ctx, now)
    return ctx


async def _member_has_manage_guild(guild_id: str, user_id: str) -> bool:
    ctx = await _guild_perm_context(guild_id)
    if ctx is None:
        return False
    owner_id, role_perms = ctx
    if owner_id and str(user_id) == owner_id:
        return True

    member_roles = await member_role_ids(guild_id, user_id)
    perms = role_perms.get(str(guild_id), 0)  # @everyone role id == guild id
    for rid in member_roles:
        perms |= role_perms.get(rid, 0)

    if perms & ADMINISTRATOR_PERMISSION:
        return True
    return (perms & MANAGE_GUILD_PERMISSION) == MANAGE_GUILD_PERMISSION


async def has_manage_guild(session: dict, guild_id: str) -> bool:
    """LIVE MANAGE_GUILD check for the session user in ``guild_id``.

    Uses the bot token to compute the user's effective permissions from their roles
    (ADMINISTRATOR or MANAGE_GUILD). Falls back to the session snapshot only when no bot
    token is configured.
    """
    if not BOT_TOKEN:
        return session_has_manage_guild(session, guild_id)
    user_id = session.get("user_id") or session.get("user_data", {}).get("id")
    if not user_id:
        return False
    return await _member_has_manage_guild(str(guild_id), str(user_id))
