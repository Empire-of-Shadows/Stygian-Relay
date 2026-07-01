"""Audit log API — relay schema: {category, guild_id:str, actor_id:str, action, payload, created_at}."""

import logging
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard import db
from dashboard.auth.dependencies import get_current_user, require_panel_access

logger = logging.getLogger(__name__)
router = APIRouter(tags=["audit_log"])

_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 100


def _serialize_entry(doc: dict) -> dict:
    out = {
        "id": str(doc["_id"]),
        "category": doc.get("category", ""),
        "guild_id": str(doc.get("guild_id", "")),
        "actor_id": str(doc.get("actor_id", "")),
        "action": doc.get("action", ""),
        "payload": doc.get("payload") or {},
        "created_at": None,
    }
    ts = doc.get("created_at")
    if isinstance(ts, datetime):
        out["created_at"] = ts.isoformat()
    elif isinstance(ts, str):
        out["created_at"] = ts
    return out


@router.get("/guilds/{guild_id}/audit-log")
async def get_audit_log(
    guild_id: str,
    category: str | None = Query(default=None),
    before: str | None = Query(default=None, description="ObjectId cursor — return entries older than this."),
    limit: int = Query(default=_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)

    gid = str(guild_id)
    query: dict = {"guild_id": gid}

    if category:
        query["category"] = category

    if before:
        try:
            query["_id"] = {"$lt": ObjectId(before)}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor value.")

    cursor = db.audit_logs().find(
        query,
        sort=[("_id", -1)],
        limit=limit,
    )
    entries = [_serialize_entry(doc) async for doc in cursor]

    next_cursor = entries[-1]["id"] if len(entries) == limit else None

    return {
        "entries": entries,
        "next_cursor": next_cursor,
    }
