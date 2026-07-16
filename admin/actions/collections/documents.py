# ───────────────────────────────────────────────────────────────────────────
# VENDORED from admin_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
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


async def insert_document(collection: str, doc: dict):
    """Insert ``doc``; returns the inserted id (or None)."""
    return await db_insert_one(collection, doc)
