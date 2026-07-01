# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
from dataclasses import dataclass
from typing import List

from pymongo import IndexModel


@dataclass
class CollectionConfig:
    """Configuration for a collection including indexes and settings.

    A bot declares one of these per collection in its ``DefineCollections`` mixin
    (see ``define_collections_reference.py``). The engine uses ``connection`` to pick a
    pool, ``database``/``name`` to resolve the collection, ``indexes`` to build indexes on
    startup, and the capped-collection fields when ``capped`` is set.
    """
    name: str
    database: str
    connection: str = 'primary'
    indexes: List[IndexModel] = None
    capped: bool = False
    max_size: int = None
    max_documents: int = None
