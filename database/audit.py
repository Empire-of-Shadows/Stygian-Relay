"""
Audit log writer. Records significant guild/premium/setting actions to the
`audit_logs` collection so abuse and disputes can be traced.

Entries TTL after 365 days (index created in GuildManager.initialize_default_settings).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("AuditLog")


class AuditLog:
    """Generic audit recorder. Hold a reference to the DatabaseCore."""

    def __init__(self, database_core):
        self.db = database_core

    async def log(
        self,
        category: str,
        guild_id: Optional[str],
        actor_id: Optional[str],
        action: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Write a single audit record.

        category: high-level bucket ("premium", "settings", "rule", "system")
        action: short verb like "redeem", "generate", "set_manager_role"
        """
        try:
            collection = self.db.get_collection("discord_forwarding_bot", "audit_logs")
            await collection.insert_one({
                "category": category,
                "guild_id": guild_id,
                "actor_id": actor_id,
                "action": action,
                "payload": payload or {},
                "created_at": datetime.now(timezone.utc),
            })
        except Exception as e:
            # Audit failures must never break the user-facing operation.
            logger.error(f"Failed to write audit entry ({category}/{action}): {e}", exc_info=True)
