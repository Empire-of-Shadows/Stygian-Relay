# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""AuditLog - generic admin/action audit writer.

Capability: append-only audit trail. Promoted from the near-identical ``AuditLogger`` in
TheHost / TheCodex / EcomRebuild (each persisted "who changed what, when, from where" for
admin-driven mutations). Genericized: the bot supplies the collection registry key; entries
are arbitrary keyword fields (JSON/Mongo-coerced) so any bot's audit shape fits, plus a
``log_config_change`` convenience for the canonical admin-panel shape every bot shares.

Retention is a property of the collection's TTL index on ``created_at`` (the bot declares it
in ``define_collections``), not of this writer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..core.collection_manager import CollectionManager
from ..logging_compat import get_logger

logger = get_logger("AuditLog")


def _to_safe(value: Any) -> Any:
    """Coerce a value into something Mongo + JSON friendly (recursively)."""
    if value is None or isinstance(value, (bool, int, float, str, datetime)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_safe(v) for v in value]
    return str(value)


class AuditLog:
    """Append audit entries to one collection. Construct with the audit ``CollectionManager``.

    Args:
        manager: the ``CollectionManager`` for the audit collection (declare a TTL index on
            ``created_at`` in ``define_collections`` for retention).
    """

    def __init__(self, manager: CollectionManager):
        self._mgr = manager

    async def log(self, **fields: Any) -> bool:
        """Capability: write one audit entry. Persists the given fields plus a UTC
        ``created_at`` timestamp; all values are coerced Mongo/JSON-safe. Best-effort - returns
        ``False`` (and logs) on error rather than raising into the caller's request."""
        try:
            doc = {k: _to_safe(v) for k, v in fields.items()}
            doc["created_at"] = datetime.now(timezone.utc)
            await self._mgr.create_one(doc)
            return True
        except Exception as e:
            logger.error(f"Failed to write audit entry {fields!r}: {e}", exc_info=True)
            return False

    async def log_config_change(
        self,
        *,
        guild_id: Any,
        actor_id: Any,
        actor_name: str,
        action: str,
        section: str = "",
        key: str = "",
        old_value: Any = None,
        new_value: Any = None,
        source: str = "discord",
        **extra: Any,
    ) -> bool:
        """Capability: write the canonical admin-config-change entry (the shape shared by every
        bot's admin panel: who/what/when/where + before→after). Extra kwargs are merged in."""
        return await self.log(
            guild_id=str(guild_id),
            actor_id=str(actor_id) if actor_id is not None else None,
            actor_name=str(actor_name)[:128],
            source=source,
            section=section,
            key=key,
            old_value=old_value,
            new_value=new_value,
            action=action,
            **extra,
        )

    async def log_many(self, entries: Iterable[dict]) -> int:
        """Capability: best-effort bulk audit. Writes each entry; returns the count written."""
        count = 0
        for entry in entries:
            if await self.log(**entry):
                count += 1
        return count
