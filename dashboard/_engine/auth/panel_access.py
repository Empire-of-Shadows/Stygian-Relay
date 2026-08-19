# VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
# Edit the master at EmpireSystems/dashboard_engine/ and run:
#     python EmpireSystems/tools/sync_dashboard_engine.py
# Drift is enforced by:
#     python EmpireSystems/tools/sync_dashboard_engine.py --check
"""Shared panel-access plumbing: live Discord permission/role checks.

Bot-agnostic machinery each dashboard's ``auth/panel_role.py`` seam builds its own tier
policy on top of. Provides the LIVE guild-permission check (``has_manage_guild`` via the bot
token, computing ADMINISTRATOR / MANAGE_GUILD from role permissions), the member-role fetch
(``member_role_ids``, and ``member_roles_lookup`` when the caller needs to know whether the
answer is trustworthy), a session-snapshot hint (``session_has_manage_guild``), plus the
internal token-bucket rate limiter and TTL caches that keep the bot-token fetches within
Discord's limits. Panel access is ADMIN-ONLY fleet-wide - a seam resolves either "admin"
or "none" - so only the role data source is per-bot.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from dashboard.config import (
    ADMINISTRATOR_PERMISSION,
    BOT_TOKEN,
    DISCORD_API_BASE,
    MANAGE_GUILD_PERMISSION,
)

logger = logging.getLogger("dashboard.auth.panel_access")

PanelRole = Literal["admin", "none"]

_MEMBER_CACHE_TTL = 60.0
# Deliberately shorter than the full TTL: an unexpected status is a symptom of
# something transient, so it should clear long before a real answer would. It
# was 60.0, which made the backdating trick at the failure branch subtract zero
# and cache the failure for the full minute - the opposite of what it says.
_MEMBER_NEGATIVE_TTL = 10.0

# Roles only, keyed by (guild_id, user_id). The value shape is load-bearing
# beyond this module: EcomRebuild's seam writes into this dict directly, so the
# lookup OUTCOME is kept in the parallel map below rather than widening this
# tuple. A key present here with no outcome entry was written by that seam,
# which only ever caches a successful fetch - so it reads back as resolved.
_member_cache: dict[tuple[str, str], tuple[frozenset[str], float]] = {}
_member_outcome: dict[tuple[str, str], tuple[bool, str]] = {}
_cache_lock = asyncio.Lock()

_guild_perm_cache: dict[str, tuple[tuple[str, dict[str, int]] | None, float]] = {}
_GUILD_PERM_TTL = 60.0
# Same reasoning as _MEMBER_NEGATIVE_TTL, and it matters more here: a None guild
# context makes _member_has_manage_guild deny immediately, so caching a transient
# failure for the full minute locked a genuine admin out of the panel for that
# minute on the strength of one bad response.
_GUILD_PERM_NEGATIVE_TTL = 10.0

# Both caches are keyed per member or per guild, so they grow with every distinct
# key seen over the process lifetime. Expired entries were skipped on read but
# never removed, which made this a slow leak in a long-running dashboard. Swept on
# write, and only once the map is big enough for the sweep to earn itself.
_CACHE_PRUNE_AT = 2048


def _prune_expired(cache: dict, ttl: float, now: float, *companions: dict) -> None:
    """Drop entries past their TTL. The caller must already hold ``_cache_lock``.

    ``companions`` are maps sharing the same keys (``_member_outcome``), dropped in
    step so an outcome cannot outlive the roles it describes.
    """
    if len(cache) < _CACHE_PRUNE_AT:
        return
    stale = [key for key, entry in cache.items() if now - entry[1] >= ttl]
    for key in stale:
        cache.pop(key, None)
        for companion in companions:
            companion.pop(key, None)


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


@dataclass(frozen=True)
class MemberRoles:
    """The OUTCOME of a member-role lookup, not just its result.

    ``resolved`` is the field that matters. False means Discord never gave us an
    answer, so ``roles`` being empty says nothing about the member - it is the
    absence of a reply, not a member who holds no roles. A bare set cannot tell
    those apart, which is the whole reason this type exists: a caller that reads
    an empty set as "holds nothing" will deny a member their entitlements during
    an outage, or - worse - skip a deny-by-role rule and report the opposite of
    the truth.

    ``reason`` is for logs and for a member-readable "we could not check right
    now", never for a decision: branch on ``resolved``.
    """

    roles: frozenset[str]
    resolved: bool
    reason: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - guard, not a decision point
        raise TypeError(
            "MemberRoles has no truth value on purpose - an unresolved lookup and a "
            "member with no roles must not collapse to the same falsy answer. "
            "Branch on .resolved, then read .roles."
        )


async def member_roles_lookup(guild_id: str, user_id: str) -> MemberRoles:
    """Live (cached) fetch of a member's role ids, carrying whether it resolved.

    Prefer this over ``member_role_ids`` anywhere an empty answer would change
    what a member is shown or allowed. Access checks that fail closed can keep
    using the plain fetch - denying on an unresolved lookup is the safe
    direction and is what they already do.
    """
    key = (str(guild_id), str(user_id))
    now = time.monotonic()
    cached = _member_cache.get(key)
    if cached is not None and now - cached[1] < _MEMBER_CACHE_TTL:
        resolved, reason = _member_outcome.get(key, (True, ""))
        return MemberRoles(cached[0], resolved, reason)

    if not BOT_TOKEN:
        return MemberRoles(frozenset(), False, "no_bot_token")

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
        return MemberRoles(frozenset(), False, "request_failed")

    if resp.status_code == 404:
        # User not a member - a real answer, cached for the full TTL.
        roles: frozenset[str] = frozenset()
    elif resp.status_code == 200:
        roles = frozenset(str(r) for r in resp.json().get("roles", []))
    else:
        logger.warning("Discord member fetch %s/%s -> %s", guild_id, user_id, resp.status_code)
        # Cache unexpected failures for the shorter negative TTL so they clear
        # quickly. The timestamp is backdated rather than stored with its own
        # expiry, so the single TTL comparison above still governs both.
        reason = f"http_{resp.status_code}"
        async with _cache_lock:
            _member_cache[key] = (frozenset(), now - (_MEMBER_CACHE_TTL - _MEMBER_NEGATIVE_TTL))
            _member_outcome[key] = (False, reason)
            _prune_expired(_member_cache, _MEMBER_CACHE_TTL, now, _member_outcome)
        return MemberRoles(frozenset(), False, reason)

    async with _cache_lock:
        _member_cache[key] = (roles, now)
        _member_outcome[key] = (True, "")
        _prune_expired(_member_cache, _MEMBER_CACHE_TTL, now, _member_outcome)
    return MemberRoles(roles, True, "")


async def member_role_ids(guild_id: str, user_id: str) -> frozenset[str]:
    """Live (cached) fetch of a member's role ids via the bot token.

    Returns an empty set when the lookup could not be resolved, which is why
    every caller of this function fails closed. Use ``member_roles_lookup`` when
    "we could not check" has to read differently from "holds no roles".
    """
    return (await member_roles_lookup(guild_id, user_id)).roles


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
        # A 404 is a real answer - the bot is not in this guild - and keeps the full
        # TTL. Anything else is transient and is backdated into the negative window,
        # because denying every admin for a minute over one 503 is worse than asking
        # Discord again in ten seconds.
        definite = resp.status_code == 404
        stamp = now if definite else now - (_GUILD_PERM_TTL - _GUILD_PERM_NEGATIVE_TTL)
        async with _cache_lock:
            _guild_perm_cache[key] = (None, stamp)
            _prune_expired(_guild_perm_cache, _GUILD_PERM_TTL, now)
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
        _prune_expired(_guild_perm_cache, _GUILD_PERM_TTL, now)
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
