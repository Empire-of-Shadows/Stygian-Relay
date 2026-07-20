# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""One-time data migrations for the Guild Configuration Engine.

The engine standardizes ``guild_id`` to ``str`` everywhere. Bots that previously stored
it as an int (TheHost, TheCodex, ImperialReminder) run ``normalize_guild_id_to_str``
once at rollout to rewrite their existing documents. Mirrors Stygian-Relay's
``_migrate_guild_id_field`` (``database/guild_manager.py``), generalized to any collection.

This is idempotent and safe to re-run: documents already storing a ``str`` id are skipped.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.collection_manager import CollectionManager
from ..logging_compat import get_logger

logger = get_logger("guild_config.migration")


async def normalize_guild_id_to_str(
    manager: CollectionManager, *, id_field: str = "guild_id"
) -> Dict[str, int]:
    """Rewrite int ``id_field`` values to ``str`` across one collection.

    Returns a summary ``{"scanned", "converted", "conflicts"}``. A "conflict" is a doc
    whose stringified id already exists as a separate ``str`` document — those are left
    untouched and reported so an operator can merge them deliberately rather than the
    migration silently clobbering data.
    """
    summary = {"scanned": 0, "converted": 0, "conflicts": 0}

    # Only documents whose id is stored as an int need rewriting.
    int_docs = await manager.find_many({"$expr": {"$eq": [{"$type": f"${id_field}"}, "int"]}})
    summary["scanned"] = len(int_docs)

    for doc in int_docs:
        raw = doc.get(id_field)
        if raw is None:
            continue
        str_id = str(raw)

        existing = await manager.find_one({id_field: str_id})
        if existing is not None:
            summary["conflicts"] += 1
            logger.warning(
                f"guild_id migration conflict on {manager.name}: int {raw!r} and str "
                f"{str_id!r} both exist; leaving the int doc in place for manual merge."
            )
            continue

        filter_doc: Dict[str, Any] = {"_id": doc["_id"]}
        await manager.update_one(filter_doc, {"$set": {id_field: str_id}}, upsert=False)
        summary["converted"] += 1

    logger.info(
        f"guild_id→str migration on {manager.name}: "
        f"scanned={summary['scanned']} converted={summary['converted']} "
        f"conflicts={summary['conflicts']}"
    )
    return summary
