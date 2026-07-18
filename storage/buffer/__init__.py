# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""storage_engine.buffer — high-frequency write buffering.

``BatchWriter`` coalesces many small writes to the same document into one MongoDB
``bulk_write``, dramatically cutting write volume for hot counters (vote tallies, reaction
stats, leaderboard increments). Promoted from EcomRebuild's
``ecom_system/helpers/batch_writer.py`` and generalized to route through the engine's
``CollectionManager`` (so flushes get retry, timestamping, and cache invalidation for free)
and to key by **collection registry key** instead of a raw collection object.

Use it only for writes that are safe to defer — atomic ``$inc`` counters and override
``$set``s. Read-modify-write logic and values returned to the caller must stay direct. See
``docs/storage_engine/write-buffering.md``.
"""

from .batch_writer import BatchWriter

__all__ = ["BatchWriter"]
