"""Panel-role resolution for the Relay dashboard.

Relay has only two tiers (no mod tier):
  - "admin": Discord MANAGE_GUILD OR the configured manager_role_id
  - "none":  no panel access

Mirrors `admin/settings/bindings.py::resolve_panel_role`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

import httpx

from dashboard import db
from dashboard.config import (
    ADMINISTRATOR_PERMISSION,
    BOT_TOKEN,
    DISCORD_API_BASE,
    MANAGE_GUILD_PERMISSION,
)

logger = logging.getLogger(__name__)

PanelRole = Literal["admin", "mod", "none"]

# Relay has no mod tier - this frozenset is intentionally empty.
MOD_ALLOWED_SECTIONS: frozenset[str] = frozenset()

_MEMBER_CACHE_TTL = 60.0
_MEMBER_NEGATIVE_TTL = 60.0

_member_cache: dict[tuple[str, str], tuple[frozenset[str], float]] = {}
_cache_lock = asyncio.Lock()

_guild_perm_cache: dict[str, tuple[tuple[str, dict[str, int]] | None, float]] = {}
_GUILD_PERM_TTL = 60.0

_RATE_CAPACITY = 5
_RATE_REFILL_PER_SEC = 20.0
_rate_tokens = float(_RATE_CAPACITY)
_rate_last_refill = time.monotonic()
_rate_lock = asyncio.Lock()


def _session_has_manage_guild(session: dict, guild_id: str) -> bool:
    for g in session.get("guilds", []):
        if str(g["id"]) == str(guild_id):
            perms = int(g.get("permissions", 0))
            return (perms & MANAGE_GUILD_PERMISSION) == MANAGE_GUILD_PERMISSION
    return False


async def _acquire_rate_slot() -> None:
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


async def _member_role_ids(guild_id: str, user_id: str) -> frozenset[str]:
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
        roles: frozenset[str] = frozenset()
    elif resp.status_code == 200:
        data = resp.json()
        roles = frozenset(str(r) for r in data.get("roles", []))
    else:
        logger.warning("Discord member fetch %s/%s -> %s", guild_id, user_id, resp.status_code)
        async with _cache_lock:
            _member_cache[key] = (frozenset(), now - (_MEMBER_CACHE_TTL - _MEMBER_NEGATIVE_TTL))
        return frozenset()

    async with _cache_lock:
        _member_cache[key] = (roles, now)
    return roles


async def _guild_perm_context(guild_id: str) -> tuple[str, dict[str, int]] | None:
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

    member_roles = await _member_role_ids(guild_id, user_id)
    perms = role_perms.get(str(guild_id), 0)
    for rid in member_roles:
        perms |= role_perms.get(rid, 0)

    if perms & ADMINISTRATOR_PERMISSION:
        return True
    return (perms & MANAGE_GUILD_PERMISSION) == MANAGE_GUILD_PERMISSION


async def has_manage_guild(session: dict, guild_id: str) -> bool:
    if not BOT_TOKEN:
        return _session_has_manage_guild(session, guild_id)
    user_id = session.get("user_id") or session.get("user_data", {}).get("id")
    if not user_id:
        return False
    return await _member_has_manage_guild(str(guild_id), str(user_id))


async def _guild_panel_roles(guild_id: str) -> tuple[list[int], list[int]]:
    """Return (admin_role_ids, mod_role_ids) for `guild_id`.

    Relay uses a single `manager_role_id` field (no mod tier).
    """
    doc = await db.guild_settings().find_one(
        {"guild_id": str(guild_id)}, projection={"manager_role_id": 1}
    )
    if not doc:
        return ([], [])
    raw = doc.get("manager_role_id")
    if not raw:
        return ([], [])
    try:
        mid = int(raw)
    except (TypeError, ValueError):
        return ([], [])
    return ([mid], [])


async def resolve_panel_role(
    session: dict, guild_id: str, *, verify_manage_live: bool = True
) -> PanelRole:
    """Resolve the user's panel access tier for `guild_id`.

    Precedence (mirrors bindings.py::resolve_panel_role):
      1. MANAGE_GUILD permission -> "admin"
      2. Configured manager_role_id -> "admin"
      3. Otherwise -> "none"
    """
    if verify_manage_live:
        if await has_manage_guild(session, guild_id):
            return "admin"
    elif _session_has_manage_guild(session, guild_id):
        return "admin"

    admin_role_ids, _ = await _guild_panel_roles(guild_id)
    if not admin_role_ids:
        return "none"

    user_id = session.get("user_id") or session.get("user_data", {}).get("id")
    if not user_id:
        return "none"

    member_roles = await _member_role_ids(str(guild_id), str(user_id))
    if not member_roles:
        return "none"

    admin_role_str = {str(r) for r in admin_role_ids}
    if admin_role_str & set(member_roles):
        return "admin"
    return "none"
