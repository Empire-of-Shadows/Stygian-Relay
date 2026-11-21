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

Create support (added 2026-11-20, additive; used by ``discord_objects.py``)::

    perms = await discord_cache.bot_guild_permissions(guild_id)
    raw = await discord_cache.guild_channels_raw(guild_id)   # with overwrites
    discord_cache.invalidate_guild(guild_id)                 # after a create
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
    "kick_members": 1 << 1,
    "ban_members": 1 << 2,
    "administrator": 1 << 3,
    "manage_channels": 1 << 4,
    "manage_guild": 1 << 5,
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
    if name == "manage_guild":
        return "Manage Server"  # Discord's own name for it
    return " ".join(part.capitalize() for part in name.split("_"))


# Permissions a role the bot hands out must not carry (owner ruling 2026-11-20).
# The same list as admin_engine/permission_checks.py DANGEROUS_ROLE_PERMISSIONS,
# which explains why; a test pins the two together.
DANGEROUS_ROLE_PERMISSIONS: tuple = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "ban_members",
    "kick_members",
)


def dangerous_role_permissions(role_perms: Optional[int]) -> List[str]:
    """Readable names of the dangerous permissions in a role's permission bits."""
    if not role_perms:
        return []
    return [
        permission_label(p) for p in DANGEROUS_ROLE_PERMISSIONS
        if int(role_perms) & PERMISSION_BITS[p]
    ]


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

    def pop(self, key: str) -> None:
        self._map.pop(key, None)

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
        # Guild feature flags (guild_features, 2026-11-20); change only with boosts.
        self._features = _BoundedTTLMap(_MAX_GUILD_ENTRIES, _GUILDS_TTL)
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

    async def guild_roles_all(self, guild_id: str) -> List[dict]:
        """Every role except @everyone, managed ones INCLUDED, sorted by position.

        For pickers that name a role a member already holds rather than one the bot
        hands out - a reward paid to whoever has Server Booster, say. ``guild_roles``
        drops managed roles because the bot cannot assign them; here that is not the
        question. Each entry carries ``managed`` so the page can say which is which.
        Empty list on failure."""
        raw = await self._guild_roles_raw(guild_id)
        roles = [
            {
                "id": r["id"],
                "name": r["name"],
                "color": r["color"],
                "position": r["position"],
                "managed": r["managed"],
            }
            for r in raw
            if str(r["id"]) != str(guild_id)
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

    # -- create support (added 2026-11-20, additive) ------------------------------
    #
    # Used by discord_objects.py, which lets a dashboard create a role or a channel
    # the way the admin panel's inline Create button does. Nothing above changes.

    async def guild_channels_raw(self, guild_id: str) -> List[dict]:
        """Every channel of every type, WITH ``permission_overwrites``. A copy, so
        callers cannot mutate the cache. Empty list on failure."""
        guild_id = str(guild_id)
        await self.guild_channels(guild_id, types=())  # warm the raw cache
        return [dict(c) for c in (self._channels.get(guild_id) or [])]

    async def guild_roles_raw(self, guild_id: str) -> List[dict]:
        """Every role, @everyone included, with ``managed`` / ``permissions``. A copy.
        Empty list on failure."""
        return [dict(r) for r in await self._guild_roles_raw(guild_id)]

    async def bot_guild_permissions(self, guild_id: str) -> Optional[int]:
        """The bot's server-wide permission bits (@everyone plus its roles; all bits
        under Administrator), or None when the bot id, roles or the bot's member
        record could not be fetched."""
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
        # No overwrites: the server-wide value is the channel formula with none.
        return compute_channel_permissions(
            guild_id, roles, bot_id, member.get("roles") or [], [],
        )

    async def bot_member_role_ids(self, guild_id: str) -> Optional[List[str]]:
        """The bot's own role ids in a guild, or None when they could not be read."""
        bot_id = await self.bot_id()
        if not bot_id:
            return None
        member = await self.guild_member(str(guild_id), bot_id)
        if member is None:
            return None
        return list(member.get("roles") or [])

    async def guild_features(self, guild_id: str) -> Optional[List[str]]:
        """The guild's Discord feature flags (``GET /guilds/{id}`` ``features``), or
        None when they could not be read. Cached like the bot guild list (300 s):
        features change only with boosts or Community settings. Added 2026-11-20
        so a dashboard can tell whether a server may have a server tag
        (``GUILD_TAGS``); additive."""
        guild_id = str(guild_id)
        hit = self._features.get(guild_id)
        if hit is not None:
            return list(hit)
        async with self._resource_locks[f"f:{guild_id}"]:
            hit = self._features.get(guild_id)
            if hit is not None:
                return list(hit)
            if not _token():
                return None
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await _get_with_retry(client, f"{_api_base()}/guilds/{guild_id}")
            if resp is None:
                return None
            features = [str(f) for f in (resp.json().get("features") or [])]
            self._features.set(guild_id, features)
            return list(features)

    def invalidate_guild(self, guild_id: str) -> None:
        """Drop a guild's cached channels and roles, so the next picker read sees
        something the dashboard just created instead of a list up to 60 s old."""
        guild_id = str(guild_id)
        self._channels.pop(guild_id)
        self._roles.pop(guild_id)


# Module-level singleton - one cache per dashboard process.
discord_cache = DiscordApiCache()
