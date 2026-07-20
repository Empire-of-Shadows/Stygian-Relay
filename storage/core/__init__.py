# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""storage_engine.core — connection pooling + collection CRUD primitives."""

from .collection_config import CollectionConfig
from .collection_manager import CollectionManager, with_retry
from .connection_pool import ConnectionPool

__all__ = ["ConnectionPool", "CollectionManager", "CollectionConfig", "with_retry"]
