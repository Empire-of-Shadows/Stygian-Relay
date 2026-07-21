# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Collection doers — generic Mongo operations through the bindings seam.

Generic over which collection (a name) and which query. Each bot's ``bindings``
adapts ``db_find``/``db_count``/``db_delete_one``/``db_delete_many``/
``db_update_one``/``db_insert_one`` to its own db manager.
"""

from __future__ import annotations

from typing import Optional

from ...settings.bindings import (
    db_find, db_count, db_delete_one, db_delete_many, db_update_one, db_insert_one,
)


async def list_documents(collection: str, query: dict, *, sort=None, limit: Optional[int] = None) -> list[dict]:
    """Return documents in ``collection`` matching ``query``."""
    return list(await db_find(collection, query, sort=sort, limit=limit))


async def count_documents(collection: str, query: dict) -> int:
    """Count documents in ``collection`` matching ``query``."""
    return int(await db_count(collection, query))


async def delete_document(collection: str, query: dict) -> bool:
    """Delete a single document matching ``query``."""
    return bool(await db_delete_one(collection, query))


async def purge_collection(collection: str, query: dict) -> int:
    """Delete every document matching ``query`` (e.g. all for one guild). Returns count."""
    return int(await db_delete_many(collection, query))


async def upsert_document(collection: str, query: dict, update: dict, *, upsert: bool = True) -> bool:
    """Apply a Mongo ``update`` to the first match (creating it when ``upsert``)."""
    return bool(await db_update_one(collection, query, update, upsert=upsert))


async def update_many_documents(collection: str, query: dict, update: dict) -> int:
    """Apply ``update`` to EVERY document matching ``query``. Returns the number modified.

    Implemented as find + per-document ``db_update_one`` so it needs no
    ``db_update_many`` binding (the seam deliberately does not expose one). Not
    atomic across documents, which is fine for the low-volume, admin-triggered
    resets it backs: a guild-wide field reset now touches all matching docs rather
    than only the first.
    """
    docs = await db_find(collection, query)
    modified = 0
    for doc in docs:
        _id = doc.get("_id")
        if _id is None:
            continue
        if await db_update_one(collection, {"_id": _id}, update, upsert=False):
            modified += 1
    return modified


async def insert_document(collection: str, doc: dict):
    """Insert ``doc``; returns the inserted id (or None)."""
    return await db_insert_one(collection, doc)
