# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""SetupGate — cached "is this guild configured enough?" gate.

Capability: cached requirement gate. The storage half of TheHost/TheCodex's
``SetupGatekeeper`` — the fast, cached predicate that event listeners hit on every message —
with the discord-facing UI (embeds, permission checks) left in the bot (the engine carries no
discord dependency).

Genericized: the bot injects a ``config_loader`` (async ``guild_id -> settings``) and a
``requirement`` predicate (``settings -> bool``). Results are cached in a bounded
``TimedLRUCache`` and the gate **fails open** on loader errors, so a transient DB blip never
blocks an already-configured guild.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping, Sequence

from ..helpers.lru_cache import TimedLRUCache
from ..logging_compat import get_logger

logger = get_logger("SetupGate")

_MISS = object()  # distinguishes a cached ``False`` from a cache miss


def _dig(settings: Mapping[str, Any], path: str) -> Any:
    """Read a dotted path out of a settings mapping (``"channels.log_channel_id"``)."""
    cur: Any = settings
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return None
        cur = cur[part]
    return cur


def require_all(*dotted_paths: str) -> Callable[[Mapping[str, Any]], bool]:
    """Build a requirement predicate that is satisfied only when **every** listed dotted path
    resolves to a truthy value — the common "all these channels/roles must be set" case."""
    def predicate(settings: Mapping[str, Any]) -> bool:
        return all(_dig(settings, p) for p in dotted_paths)
    return predicate


class SetupGate:
    """Cached gate over a per-guild requirement predicate.

    Args:
        config_loader: async ``(guild_id) -> settings mapping`` (e.g.
            ``GuildConfigStore.get_settings``).
        requirement: ``(settings) -> bool`` deciding whether setup is complete. Build one with
            ``require_all("channels.a", "channels.b")`` or pass your own.
        max_size / ttl: bound and freshness (seconds) of the result cache.
    """

    def __init__(
        self,
        config_loader: Callable[[Any], Awaitable[Mapping[str, Any]]],
        requirement: Callable[[Mapping[str, Any]], bool],
        *,
        max_size: int = 200,
        ttl: int = 120,
    ):
        self._load = config_loader
        self._requirement = requirement
        self._cache = TimedLRUCache(max_size=max_size, timeout=ttl)

    async def _evaluate(self, guild_id: Any) -> bool:
        settings = await self._load(guild_id)
        return bool(self._requirement(settings))

    async def is_complete(self, guild_id: Any) -> bool:
        """Capability: cached setup check. Returns the cached verdict when fresh, else
        evaluates the requirement and caches it. Fails open (``True``) on loader errors."""
        key = str(guild_id)
        cached = self._cache.get(key, _MISS)
        if cached is not _MISS:
            return cached
        try:
            result = await self._evaluate(guild_id)
        except Exception as e:
            logger.error(f"SetupGate check failed for guild {guild_id}, failing open: {e}")
            return True
        self._cache.set(key, result)
        return result

    async def evaluate(self, guild_id: Any) -> bool:
        """Capability: re-evaluate now (bypass + refresh the cache). Call after an admin saves
        config. Returns the fresh verdict (``False`` on error, since the caller is acting on a
        known change)."""
        try:
            result = await self._evaluate(guild_id)
        except Exception as e:
            logger.error(f"SetupGate evaluate failed for guild {guild_id}: {e}", exc_info=True)
            result = False
        self._cache.set(str(guild_id), result)
        return result

    def invalidate(self, guild_id: Any) -> None:
        """Drop one guild's cached verdict."""
        self._cache.delete(str(guild_id))

    def invalidate_all(self) -> None:
        """Drop every cached verdict."""
        self._cache.clear()

    def get_stats(self) -> dict:
        """Cache hit/miss diagnostics."""
        return self._cache.get_stats()
