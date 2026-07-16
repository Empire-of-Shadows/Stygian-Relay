# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""storage_engine.content — read-through cache for semi-static content.

``CachedLoader`` is a thin async read-through over the shared ``TimedLRUCache`` primitive,
for content that is read often and written rarely and/or is expensive to rebuild: guide page
trees, WYR question banks, embed templates. It avoids re-fetching/re-serializing the same
payload on every request (e.g. TheCodex ``WYR.get_next_question`` re-querying per post, guide
index rebuilds).

It deliberately introduces no new storage — it caches whatever an async ``loader`` returns,
keyed (optionally per-guild) with TTL + LRU bounds. See
``docs/storage_engine/content-cache.md``.
"""

from .cached_loader import CachedLoader

__all__ = ["CachedLoader"]
