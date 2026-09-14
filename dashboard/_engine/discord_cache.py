# VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
# Edit the master at EmpireSystems/dashboard_engine/ and run:
#     python EmpireSystems/tools/sync_dashboard_engine.py
# Drift is enforced by:
#     python EmpireSystems/tools/sync_dashboard_engine.py --check
"""TTL + single-flight caches for bot-token Discord API reads.

Promoted from the near-identical blocks in TheCodex's and ImperialReminder's
``routers/dashboard.py``: every dashboard needs the same four reads (which guilds
is the bot in, the bot's own id for the invite URL, a guild's text channels, a
guild's assignable roles), each cached with a short TTL and a single-flight lock
so concurrent requests cannot stampede the Discord API into 429s.

Reads bot credentials from the seam (``config.BOT_TOKEN`` / ``config.DISCORD_API_BASE``)
at call time. All methods are fail-soft: on a Discord error they log, return the
last cached value (or an empty result), and never raise - the caller decides
whether an empty result is a 503. Per-guild caches are BOUNDED (oldest-entry
eviction) so a many-guild deployment cannot grow them without limit.

Usage (in a bot's ``routers/dashboard.py``)::

    from dashboard._engine.discord_cache import discord_cache

    bot_guild_ids = await discord_cache.bot_guild_ids()
    channels = await discord_cache.guild_text_channels(guild_id)
    roles = await discord_cache.guild_roles(guild_id)
    bot_id = await discord_cache.bot_id()

Settings validation (added 2026-09-13, additive - the picker payloads above are
unchanged)::

    role = await discord_cache.guild_role(guild_id, role_id)      # managed / mentionable
    perms = await discord_cache.bot_channel_permissions(guild_id, channel_id)
    missing = missing_permissions(perms, ["view_channel", "send_messages"])
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

import httpx

from dashboard import config as _config

logger = logging.getLogger("dashboard.discord_cache")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# TTLs match the values every dashboard already used.
_GUILDS_TTL = 300.0  # bot guild list + bot id
_RESOURCE_TTL = 60.0  # per-guild channels/roles/members
_MAX_MEMBER_ENTRIES = 2000  # guild:user pairs; one page of names is a few dozen at most
_MAX_GUILD_ENTRIES = 512  # bound on the per-guild caches (oldest evicted)


# Discord permission bits used by settings validation (discord.com/developers/docs/topics/permissions).
PERMISSION_BITS: Dict[str, int] = {
    "administrator": 1 << 3,
    "manage_channels": 1 << 4,
    "add_reactions": 1 << 6,
    "view_channel": 1 << 10,
    "send_messages": 1 << 11,
    "manage_messages": 1 << 13,
    "embed_links": 1 << 14,
    "attach_files": 1 << 15,
    "read_message_history": 1 << 16,
    "mention_everyone": 1 << 17,
    "manage_roles": 1 << 28,
    "manage_threads": 1 << 34,
    "create_public_threads": 1 << 35,
    "send_messages_in_threads": 1 << 38,
}
_ALL_PERMISSIONS = (1 << 53) - 1


def permission_label(name: str) -> str:
    """'read_message_history' -> 'Read Message History'."""
    return " ".join(part.capitalize() for part in name.split("_"))


def compute_channel_permissions(
    guild_id: str,
    roles: List[dict],
    member_id: str,
    member_role_ids: List[str],
    overwrites: List[dict],
) -> int:
    """A member's effective permissions in one channel, per Discord's documented order.

    ``roles`` are raw role dicts carrying ``id`` and ``permissions`` (the @everyone
    role's id is the guild id); ``overwrites`` are the channel's raw
    ``permission_overwrites`` (``id``, ``type`` 0 role / 1 member, ``allow``, ``deny``).
    Guild owners are not handled: this is for checking what a BOT can do.
    """
    guild_id = str(guild_id)
    by_id = {str(r["id"]): int(r.get("permissions") or 0) for r in roles}
    member_roles = {str(r) for r in member_role_ids}

    perms = by_id.get(guild_id, 0)
    for rid in member_roles:
        perms |= by_id.get(rid, 0)
    if perms & PERMISSION_BITS["administrator"]:
        return _ALL_PERMISSIONS

    ow = {str(o["id"]): o for o in (overwrites or [])}
    everyone = ow.get(guild_id)
    if everyone:
        perms &= ~int(everyone.get("deny") or 0)
        perms |= int(everyone.get("allow") or 0)

    allow = deny = 0
    for o in overwrites or []:
        if int(o.get("type", 0)) == 0 and str(o["id"]) in member_roles:
            allow |= int(o.get("allow") or 0)
            deny |= int(o.get("deny") or 0)
    perms &= ~deny
    perms |= allow

    member = ow.get(str(member_id))
    if member and int(member.get("type", 1)) == 1:
        perms &= ~int(member.get("deny") or 0)
        perms |= int(member.get("allow") or 0)
    return perms


def missing_permissions(perms: Optional[int], names: List[str]) -> List[str]:
    """The names in ``names`` that ``perms`` lacks. Empty when ``perms`` is None
    (could not be computed): callers fail open, like the other lookups here."""
    if perms is None:
        return []
    return [n for n in names if not perms & PERMISSION_BITS[n]]


def _token() -> str:
    return getattr(_config, "BOT_TOKEN", "") or ""


def _api_base() -> str:
    return getattr(_config, "DISCORD_API_BASE", "https://discord.com/api/v10")


async def _get_with_retry(client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
    """One GET with a single 429 retry. Returns None on non-200."""
    headers = {"Authorization": f"Bot {_token()}"}
    resp = await client.get(url, headers=headers)
    if resp.status_code == 429:
        retry_after = float(resp.headers.get("Retry-After", "2"))
        logger.info("Discord rate-limited on %s, retrying in %.1fs", url, retry_after)
        await asyncio.sleep(retry_after)
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        logger.warning("Discord GET %s failed: %s", url, resp.status_code)
        return None
    return resp


class _BoundedTTLMap:
    """guild_id -> {"data": ..., "ts": float}, evicting the oldest past a size cap."""

    def __init__(self, max_entries: int, ttl: float):
        self._map: Dict[str, Dict[str, Any]] = {}
        self._max = max_entries
        self._ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        entry = self._map.get(key)
        if entry and time.monotonic() - entry["ts"] < self._ttl:
            return entry["data"]
        return None

    def set(self, key: str, data: Any) -> None:
        if key not in self._map and len(self._map) >= self._max:
            oldest = min(self._map, key=lambda k: self._map[k]["ts"])
            self._map.pop(oldest, None)
        self._map[key] = {"data": data, "ts": time.monotonic()}


class DiscordApiCache:
    """The four shared bot-token reads, TTL-cached and single-flighted."""

    def __init__(self):
        self._bot_guilds: Set[str] = set()
        self._bot_guilds_ts = 0.0
        self._bot_guilds_lock = asyncio.Lock()

        self._bot_id: Optional[str] = None
        self._bot_id_ts = 0.0
        self._bot_id_lock = asyncio.Lock()

        self._channels = _BoundedTTLMap(_MAX_GUILD_ENTRIES, _RESOURCE_TTL)
        self._roles = _BoundedTTLMap(_MAX_GUILD_ENTRIES, _RESOURCE_TTL)
        # Single-member lookups, keyed "guild:user". Same TTL as the other per-guild
        # resources; a miss (left the guild, bad id) is cached too so a page that shows
        # many names does not re-ask Discord for the same absent member on every render.
        self._members = _BoundedTTLMap(_MAX_MEMBER_ENTRIES, _RESOURCE_TTL)
        # Per-guild single-flight locks; pruned alongside the caches by virtue of
        # being recreated rarely (a lock per active guild, bounded in practice by
        # the caches above - stale locks are just idle asyncio.Lock objects).
        self._resource_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # -- bot guild list ---------------------------------------------------------

    async def bot_guild_ids(self) -> Set[str]:
        """The set of guild ids the bot is in (paginated; stale-on-error)."""
        if not _token():
            return set()
        now = time.monotonic()
        if self._bot_guilds and now - self._bot_guilds_ts < _GUILDS_TTL:
            return self._bot_guilds

        async with self._bot_guilds_lock:
            now = time.monotonic()
            if self._bot_guilds and now - self._bot_guilds_ts < _GUILDS_TTL:
                return self._bot_guilds

            guild_ids: Set[str] = set()
            after = "0"
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                while True:
                    url = f"{_api_base()}/users/@me/guilds?limit=200&after={after}"
                    resp = await _get_with_retry(client, url)
                    if resp is None:
                        return self._bot_guilds or guild_ids
                    guilds = resp.json()
                    if not guilds:
                        break
                    for g in guilds:
                        guild_ids.add(g["id"])
                    if len(guilds) < 200:
                        break
                    after = guilds[-1]["id"]

            self._bot_guilds = guild_ids
            self._bot_guilds_ts = now
            return guild_ids

    # -- bot id (invite URL) ----------------------------------------------------

    async def bot_id(self) -> Optional[str]:
        """The bot's own user id (for building the invite URL). None on failure."""
        if not _token():
            return None
        now = time.monotonic()
        if self._bot_id and now - self._bot_id_ts < _GUILDS_TTL:
            return self._bot_id

        async with self._bot_id_lock:
            now = time.monotonic()
            if self._bot_id and now - self._bot_id_ts < _GUILDS_TTL:
                return self._bot_id
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await _get_with_retry(client, f"{_api_base()}/users/@me")
                if resp is None:
                    return self._bot_id
                self._bot_id = resp.json()["id"]
                self._bot_id_ts = now
                return self._bot_id

    # -- per-guild resources ----------------------------------------------------

    async def guild_channels(self, guild_id: str, types: tuple = (0,)) -> List[dict]:
        """Guild channels filtered to ``types``, sorted by position.

        The RAW channel list (all types, with ``parent_id``) is what's cached,
        so different callers can request different type filters (text-only
        pickers vs category+text panels like TheHost's ``game_category_id``
        select) off one fetch. Returns a NEW list per call - callers may
        re-sort freely. Empty list on failure.
        """
        guild_id = str(guild_id)
        raw = self._channels.get(guild_id)
        if raw is None:
            async with self._resource_locks[f"c:{guild_id}"]:
                raw = self._channels.get(guild_id)
                if raw is None:
                    if not _token():
                        return []
                    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                        resp = await _get_with_retry(
                            client, f"{_api_base()}/guilds/{guild_id}/channels"
                        )
                        if resp is None:
                            return []
                    raw = [
                        {
                            "id": ch["id"],
                            "name": ch["name"],
                            "type": ch["type"],
                            "parent_id": ch.get("parent_id"),
                            "position": ch.get("position", 0),
                            "permission_overwrites": ch.get("permission_overwrites") or [],
                        }
                        for ch in resp.json()
                    ]
                    self._channels.set(guild_id, raw)

        # Overwrites stay internal (bot_channel_permissions); the picker payload
        # keeps its original shape.
        channels = [
            {k: v for k, v in ch.items() if k != "permission_overwrites"}
            for ch in raw if ch["type"] in types
        ]
        channels.sort(key=lambda c: c["position"])
        return channels

    async def guild_member(self, guild_id: str, user_id: str) -> Optional[dict]:
        """One guild member as ``{"id", "display_name", "username"}``, or ``None``.

        ``display_name`` follows discord.py's ``Member.display_name`` precedence: guild
        nickname, then global display name, then username. A plain REST fetch that
        needs no privileged intent. ``None`` when the member is not in the guild, the id
        is malformed, or Discord cannot be reached - callers fall back to whatever
        name they already hold.
        """
        guild_id = str(guild_id)
        user_id = str(user_id)
        if not user_id.isdigit():
            return None
        key = f"{guild_id}:{user_id}"
        hit = self._members.get(key)
        if hit is not None:
            return hit or None
        async with self._resource_locks[f"m:{key}"]:
            hit = self._members.get(key)
            if hit is not None:
                return hit or None
            if not _token():
                return None
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await _get_with_retry(
                    client, f"{_api_base()}/guilds/{guild_id}/members/{user_id}"
                )
            if resp is None:
                self._members.set(key, {})
                return None
            raw = resp.json()
            user = raw.get("user") or {}
            member = {
                "id": str(user.get("id") or user_id),
                "display_name": (
                    raw.get("nick") or user.get("global_name") or user.get("username") or ""
                ),
                "username": user.get("username") or "",
                "roles": [str(r) for r in raw.get("roles") or []],
            }
            self._members.set(key, member)
            return member

    async def guild_text_channels(self, guild_id: str) -> List[dict]:
        """Text channels (type 0) sorted by position. Empty list on failure."""
        return await self.guild_channels(guild_id, types=(0,))

    async def _guild_roles_raw(self, guild_id: str) -> List[dict]:
        """Every role in the guild, @everyone included, with the fields validation
        needs (managed, mentionable, permissions). Empty list on failure."""
        guild_id = str(guild_id)
        cached = self._roles.get(guild_id)
        if cached is not None:
            return cached

        async with self._resource_locks[f"r:{guild_id}"]:
            cached = self._roles.get(guild_id)
            if cached is not None:
                return cached
            if not _token():
                return []
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await _get_with_retry(
                    client, f"{_api_base()}/guilds/{guild_id}/roles"
                )
                if resp is None:
                    return []
            roles = [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "color": r.get("color", 0),
                    "position": r.get("position", 0),
                    "managed": bool(r.get("managed", False)),
                    "mentionable": bool(r.get("mentionable", False)),
                    "permissions": int(r.get("permissions") or 0),
                }
                for r in resp.json()
            ]
            self._roles.set(guild_id, roles)
            return roles

    async def guild_roles(self, guild_id: str) -> List[dict]:
        """Assignable roles (position > 0, not managed) sorted by position.
        Empty list on failure."""
        raw = await self._guild_roles_raw(guild_id)
        roles = [
            {
                "id": r["id"],
                "name": r["name"],
                "color": r["color"],
                "position": r["position"],
            }
            for r in raw
            if r["position"] > 0 and not r["managed"]
        ]
        roles.sort(key=lambda r: r["position"])
        return roles

    async def guild_role(self, guild_id: str, role_id: str) -> Optional[dict]:
        """One role with ``managed``/``mentionable``/``permissions``, or None when it is
        not in the guild or the roles could not be fetched."""
        for r in await self._guild_roles_raw(guild_id):
            if str(r["id"]) == str(role_id):
                return dict(r)
        return None

    async def bot_channel_permissions(self, guild_id: str, channel_id: str) -> Optional[int]:
        """The bot's effective permission bits in a channel, or None when any input
        (bot id, roles, the bot's member record, the channel) could not be fetched."""
        guild_id = str(guild_id)
        bot_id = await self.bot_id()
        if not bot_id:
            return None
        roles = await self._guild_roles_raw(guild_id)
        if not roles:
            return None
        member = await self.guild_member(guild_id, bot_id)
        if member is None:
            return None
        await self.guild_channels(guild_id, types=())  # warm the raw cache
        raw = self._channels.get(guild_id) or []
        channel = next((c for c in raw if str(c["id"]) == str(channel_id)), None)
        if channel is None:
            return None
        return compute_channel_permissions(
            guild_id, roles, bot_id, member.get("roles") or [],
            channel.get("permission_overwrites") or [],
        )


# Module-level singleton - one cache per dashboard process.
discord_cache = DiscordApiCache()
