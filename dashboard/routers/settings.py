"""Guild configuration GET/PUT - top-level settings only (no rules here)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard import db
from dashboard.auth.dependencies import get_current_user, require_panel_access
from dashboard.services import audit

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
    # An explicit null in the request body means "clear this field"; an omitted field
    # means "leave it alone". model_fields_set distinguishes the two so a stale value
    # (e.g. a manager role) can actually be revoked from the dashboard (BUG-R7b).
    provided = body.model_fields_set

    if "master_log_channel_id" in provided:
        if body.master_log_channel_id is None:
            set_fields["master_log_channel_id"] = None
        else:
            try:
                # Stored as a STRING: the ecosystem convention is string ids, and
                # the panel already writes strings here. int() is kept purely as the
                # validation that this is a real snowflake.
                set_fields["master_log_channel_id"] = str(int(body.master_log_channel_id))
            except ValueError:
                raise HTTPException(status_code=400, detail="master_log_channel_id must be a valid integer snowflake.")

    if "manager_role_id" in provided:
        if body.manager_role_id is None:
            set_fields["manager_role_id"] = None
        else:
            try:
                # String, for the same reason as master_log_channel_id above.
                set_fields["manager_role_id"] = str(int(body.manager_role_id))
            except ValueError:
                raise HTTPException(status_code=400, detail="manager_role_id must be a valid integer snowflake.")

    if body.is_enabled is not None:
        # The runtime gates forwarding on features.forwarding_enabled; the top-level
        # is_enabled flag is only used for this dashboard's own display. Keep both in
        # sync so the toggle actually switches forwarding on/off (BUG-R7a).
        set_fields["is_enabled"] = body.is_enabled
        if not (body.features and "forwarding_enabled" in body.features):
            set_fields["features.forwarding_enabled"] = body.is_enabled

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

    # Recorded after the write, and only once it matched, so the history never claims a
    # change that did not happen. The field NAMES are stored, not their values: a log
    # channel or a manager role is a snowflake nobody can read back, and the current
    # value is one click away on the settings page. `set_fields` is used rather than the
    # request body so the mirrored `features.forwarding_enabled` write shows up too.
    await audit.record(
        session,
        category="settings",
        guild_id=gid,
        action="update_config",
        payload={"fields": sorted(set_fields.keys())},
    )

    return {"ok": True}
