# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
from dataclasses import dataclass
from typing import List, Optional

from pymongo import IndexModel


@dataclass
class CollectionConfig:
    """Configuration for a collection including indexes and settings.

    A bot declares one of these per collection in its collection registry
    (see ``Settings/storage/collections_reference.py``). The engine uses ``connection`` to pick a
    pool, ``database``/``name`` to resolve the collection, ``indexes`` to build indexes on
    startup, and the capped-collection fields when ``capped`` is set.

    ``accessor`` is an optional short attribute name: when set, the manager exposes this
    collection as ``db_manager.<accessor>`` (e.g. ``accessor="guild_config"`` →
    ``db_manager.guild_config``). Collections are always reachable by their registry key too,
    so this is pure sugar — omit it to access by key.
    """
    name: str
    database: str
    connection: str = 'primary'
    indexes: List[IndexModel] = None
    accessor: Optional[str] = None
    capped: bool = False
    max_size: int = None
    max_documents: int = None
