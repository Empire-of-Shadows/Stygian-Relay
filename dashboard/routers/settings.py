"""Guild configuration GET/PUT — top-level settings only (no rules here)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard import db
from dashboard.auth.dependencies import get_current_user, require_panel_access

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])

_MUTABLE_FIELDS = {
    "master_log_channel_id",
    "manager_role_id",
    "is_enabled",
    "features",
    "inbound_allowed_guilds",
}


@router.get("/guilds/{guild_id}/config")
async def get_config(guild_id: str, session: dict = Depends(get_current_user)):
    await require_panel_access(session, guild_id)
    gid = str(guild_id)

    doc = await db.guild_settings().find_one(
        {"guild_id": gid},
        {
            "_id": 0,
            "guild_id": 1,
            "master_log_channel_id": 1,
            "manager_role_id": 1,
            "is_enabled": 1,
            "premium_tier": 1,
            "features": 1,
            "limits": 1,
            "inbound_allowed_guilds": 1,
        },
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Guild configuration not found.")

    doc["guild_id"] = str(doc.get("guild_id", gid))
    if doc.get("master_log_channel_id") is not None:
        doc["master_log_channel_id"] = str(doc["master_log_channel_id"])
    if doc.get("manager_role_id") is not None:
        doc["manager_role_id"] = str(doc["manager_role_id"])

    inbound = doc.get("inbound_allowed_guilds") or []
    doc["inbound_allowed_guilds"] = [str(g) for g in inbound]

    return doc


class UpdateConfigRequest(BaseModel):
    master_log_channel_id: str | None = None
    manager_role_id: str | None = None
    is_enabled: bool | None = None
    features: dict | None = None
    inbound_allowed_guilds: list[str] | None = None


@router.put("/guilds/{guild_id}/config")
async def update_config(
    guild_id: str,
    body: UpdateConfigRequest,
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)
    gid = str(guild_id)

    set_fields: dict = {}

    if body.master_log_channel_id is not None:
        try:
            set_fields["master_log_channel_id"] = int(body.master_log_channel_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="master_log_channel_id must be a valid integer snowflake.")

    if body.manager_role_id is not None:
        try:
            set_fields["manager_role_id"] = int(body.manager_role_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="manager_role_id must be a valid integer snowflake.")

    if body.is_enabled is not None:
        set_fields["is_enabled"] = body.is_enabled

    if body.features is not None:
        for k, v in body.features.items():
            set_fields[f"features.{k}"] = v

    if body.inbound_allowed_guilds is not None:
        try:
            set_fields["inbound_allowed_guilds"] = [int(g) for g in body.inbound_allowed_guilds]
        except ValueError:
            raise HTTPException(status_code=400, detail="inbound_allowed_guilds must contain valid integer snowflakes.")

    if not set_fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    result = await db.guild_settings().update_one(
        {"guild_id": gid},
        {"$set": set_fields},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Guild configuration not found.")

    return {"ok": True}
