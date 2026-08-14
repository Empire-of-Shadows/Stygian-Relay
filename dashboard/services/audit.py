"""Audit writing from the dashboard.

Correctness fix, not a feature: until now the dashboard could change a server's settings
and create, edit, pause or delete a forwarding rule and write NOTHING to ``audit_logs``.
The same actions done from the ``/admin`` panel in Discord were recorded. So a server's
change history quietly depended on which surface the admin happened to use, and the
overview's "last change" line could be months stale on a server that was being managed
entirely from the web.

The document shape is a byte-for-byte match for the bot's writer
(``storage/bot_specific/relay/audit/writer.py``) - same five fields, same
``created_at`` as a timezone-aware UTC datetime, so the audit-log API and the 365-day TTL
index treat both writers' entries identically. It is re-implemented here rather than
imported because the dashboard is deliberately standalone and does not import the bot's
packages; if the bot's shape ever changes, this file changes with it.

``actor_name`` rides inside ``payload`` rather than being promoted to a top-level field:
the collection's shape is the bot's to change, and the audit-log page reads names out of
the payload. Storing the name as well as the id is deliberate - an id alone is unreadable
in a history, and by the time someone reads it the member may have left the server.

Audit failures never break the user-facing operation. A settings save that succeeded must
not report failure because the history write did not land.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from dashboard import db

logger = logging.getLogger(__name__)


def actor_of(session: dict) -> tuple[str, str]:
    """(actor_id, actor_name) from a session. Name falls back to the id."""
    user = session.get("user_data") or {}
    actor_id = str(user.get("id") or session.get("user_id") or "")
    actor_name = user.get("global_name") or user.get("username") or actor_id
    return actor_id, str(actor_name)


async def record(
    session: dict,
    *,
    category: str,
    guild_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Write one audit entry for a dashboard action. Never raises."""
    actor_id, actor_name = actor_of(session)
    entry_payload: dict[str, Any] = {"actor_name": actor_name, "source": "dashboard"}
    if payload:
        entry_payload.update(payload)
    try:
        await db.audit_logs().insert_one({
            "category": category,
            "guild_id": str(guild_id),
            "actor_id": actor_id,
            "action": action,
            "payload": entry_payload,
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.error(
            "Failed to write dashboard audit entry (%s/%s): %s", category, action, e,
            exc_info=True,
        )
