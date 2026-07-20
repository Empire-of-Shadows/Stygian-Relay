# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""storage_engine.cache — the pluggable, hit-first cache layer.

One interface (``CacheBackend``), multiple backends. v1 ships ``LocalCache`` (in-process
TTL + LRU); ``RedisCache`` is a reserved slot for a future shared/cross-process backend.
``ChangeStreamWatcher`` keeps a cache coherent with MongoDB in real time via change
streams, degrading gracefully to TTL-only when change streams are unavailable.

The backend a bot uses is chosen in its ``storage/bindings.py`` (``CACHE_BACKEND``); the
engine never hard-codes one.
"""

from .backend import CacheBackend
from .local import LocalCache
from .coherency import ChangeStreamWatcher

__all__ = ["CacheBackend", "LocalCache", "ChangeStreamWatcher"]
