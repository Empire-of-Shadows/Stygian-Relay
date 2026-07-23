# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""ChangeStreamWatcher - keep the cache coherent with MongoDB in real time.

The local cache is hit FIRST on reads. That is safe against this process's own writes
(they call ``cache.invalidate``), but another writer - a second bot instance, the web
hub, a manual DB edit - would otherwise leave us serving stale data until the TTL lapses.
MongoDB change streams close that gap: we subscribe to ``collection.watch()`` and drop
the affected collection's cache entries the instant a change lands, from the
authoritative source (the database itself).

Generalizes EcomRebuild's per-config watcher (``storage/config_manager.py`` ``_watch_loop``)
to any set of collections.

IMPORTANT - replica-set requirement: change streams only exist on a replica set (or
sharded cluster). A standalone ``mongod`` raises on ``watch()``. This watcher detects that,
logs ONCE, and stops cleanly - the cache then relies on TTL expiry alone (still correct,
just not instantaneous). So enabling/ disabling coherency is a deployment property, not a
code change.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Iterable, Optional

from pymongo.errors import OperationFailure, PyMongoError

from ..cache.backend import CacheBackend
from ..logging_compat import get_logger

logger = get_logger("ChangeStreamWatcher")


class ChangeStreamWatcher:
    """Watches ``watched`` collections and invalidates their cache keys on any change.

    Parameters
    ----------
    collection_provider:
        ``callable(name) -> raw async Mongo collection`` (e.g.
        ``db_manager.get_raw_collection`` or a closure over a CollectionManager's
        ``.collection``).
    cache:
        the shared ``CacheBackend`` whose entries are keyed ``"<collection>:<...>"``.
    watched:
        collection names to attach a change stream to. Empty => watcher is a no-op
        (pure TTL coherency).
    on_change:
        optional ``callable(collection_name, change_doc)`` invoked after the cache
        namespace is invalidated. Lets side-caches that do not live in the shared
        ``CacheBackend`` (a SetupGate's TimedLRUCache, a typed config wrapper's
        memo) invalidate in the same beat. Exceptions are swallowed and logged.
    on_degraded:
        optional ``callable(collection_name)`` invoked once when a collection's
        stream degrades to TTL-only (standalone mongod, unexpected error). Lets
        the owner shorten its cache TTL as the cross-process freshness fallback
        (EcomRebuild pattern: 300s -> 30s).
    """

    def __init__(
        self,
        collection_provider: Callable[[str], object],
        cache: CacheBackend,
        watched: Iterable[str],
        *,
        full_document: str = "updateLookup",
        on_change: Optional[Callable[[str, dict], None]] = None,
        on_degraded: Optional[Callable[[str], None]] = None,
    ):
        self._provider = collection_provider
        self._cache = cache
        self._watched = list(watched)
        self._full_document = full_document
        self._on_change = on_change
        self._on_degraded = on_degraded
        self._tasks: list[asyncio.Task] = []
        self._stopped = asyncio.Event()
        self._degraded = False  # True once we fall back to TTL-only

    @property
    def degraded(self) -> bool:
        """True if change streams were unavailable and we fell back to TTL-only."""
        return self._degraded

    async def start(self) -> None:
        """Spawn one watch loop per collection. Returns immediately."""
        if not self._watched:
            logger.debug("No watched collections; coherency is TTL-only.")
            return
        for name in self._watched:
            self._tasks.append(asyncio.create_task(self._watch_loop(name), name=f"watch:{name}"))
        logger.info(f"ChangeStreamWatcher started for {len(self._tasks)} collection(s).")

    async def _watch_loop(self, name: str) -> None:
        try:
            collection = self._provider(name)
        except Exception as e:  # provider couldn't resolve the collection
            logger.warning(f"Cannot watch {name!r}: {e}")
            return

        resume_token = None
        backoff_s = 1.0
        while not self._stopped.is_set():
            try:
                # pymongo's async watch() is a *coroutine*: it must be awaited before
                # the returned change stream can be used as an async context manager.
                stream = await collection.watch(
                    full_document=self._full_document,
                    resume_after=resume_token,
                )
                async with stream:
                    logger.debug(f"Watching change stream on {name!r}")
                    backoff_s = 1.0  # reset after a successful (re)subscribe
                    async for change in stream:
                        if self._stopped.is_set():
                            break
                        resume_token = stream.resume_token
                        self._invalidate_for(name, change)
            except asyncio.CancelledError:
                raise
            except OperationFailure as e:
                # Most commonly: not running on a replica set -> change streams
                # unsupported. No point retrying; degrade to TTL-only and stop.
                self._degraded = True
                logger.warning(
                    f"Change streams unavailable for {name!r} ({e}); "
                    f"falling back to TTL-only coherency for this collection."
                )
                self._notify_degraded(name)
                return
            except PyMongoError as e:
                # Transient (primary stepdown, network blip): resume from the last
                # token after a bounded backoff instead of giving up permanently.
                logger.warning(
                    f"Change-stream error on {name!r} ({e}); resuming in {backoff_s:.0f}s."
                )
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=backoff_s)
                except asyncio.TimeoutError:
                    pass
                backoff_s = min(backoff_s * 2, 30.0)
            except Exception as e:  # never let a watcher crash take down the bot
                self._degraded = True
                logger.error(f"Unexpected change-stream error on {name!r}: {e}", exc_info=True)
                self._notify_degraded(name)
                return

    def _invalidate_for(self, name: str, change: dict) -> None:
        """Drop cache entries for the changed collection. We invalidate the whole
        collection namespace (cheap, in-process) rather than guess per-document keys."""
        removed = self._cache.invalidate(f"{name}:")
        op = change.get("operationType", "?") if isinstance(change, dict) else "?"
        logger.debug(f"Invalidated {removed} cache entr(y/ies) for {name!r} after {op}.")
        if self._on_change is not None:
            try:
                self._on_change(name, change if isinstance(change, dict) else {})
            except Exception as e:
                logger.error(f"on_change hook failed for {name!r}: {e}", exc_info=True)

    def _notify_degraded(self, name: str) -> None:
        if self._on_degraded is not None:
            try:
                self._on_degraded(name)
            except Exception as e:
                logger.error(f"on_degraded hook failed for {name!r}: {e}", exc_info=True)

    async def stop(self) -> None:
        """Cancel all watch loops."""
        self._stopped.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("ChangeStreamWatcher stopped.")
