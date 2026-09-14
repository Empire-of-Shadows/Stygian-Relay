"""Guild configuration GET/PUT - top-level settings only (no rules here)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard import db
from dashboard._engine.auth.panel_access import has_manage_guild
from dashboard._engine.discord_cache import discord_cache, missing_permissions, permission_label
from dashboard.auth.dependencies import get_current_user, require_panel_access
from dashboard.services import audit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])

#: The two switches under ``features``. Anything else is refused rather than written into
#: the settings document, where nothing reads it.
FEATURE_KEYS = ("forwarding_enabled", "notify_on_error")

#: What the bot needs in the log channel: it posts embeds there unprompted (rules it had
#: to switch off, premium changes). Same set the Discord panel refuses a channel without.
LOG_CHANNEL_PERMS = ["view_channel", "send_messages", "embed_links"]


def _features(doc: dict) -> dict:
    """The two switches, a missing one reading ON the way the bot reads it."""
    stored = doc.get("features") or {}
    return {key: bool(stored.get(key, True)) for key in FEATURE_KEYS}


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
    doc["features"] = _features(doc)

    inbound = doc.get("inbound_allowed_guilds") or []
    doc["inbound_allowed_guilds"] = [str(g) for g in inbound]

    return doc


class UpdateConfigRequest(BaseModel):
    master_log_channel_id: str | None = None
    manager_role_id: str | None = None
    features: dict[str, bool] | None = None
    inbound_allowed_guilds: list[str] | None = None


@router.put("/guilds/{guild_id}/config")
async def update_config(
    guild_id: str,
    body: UpdateConfigRequest,
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)
    gid = str(guild_id)

    before = await db.guild_settings().find_one(
        {"guild_id": gid}, {"_id": 0, "manager_role_id": 1, "master_log_channel_id": 1},
    )
    if before is None:
        raise HTTPException(status_code=404, detail="Guild configuration not found.")

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

    if body.features is not None:
        unknown = sorted(set(body.features) - set(FEATURE_KEYS))
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown feature switch: {', '.join(unknown)}.",
            )
        # features.forwarding_enabled is the one switch the forwarder reads; the panel
        # writes the same key. (A separate is_enabled display flag used to be shown here
        # instead, so the two screens disagreed whenever the panel changed forwarding.)
        for k, v in body.features.items():
            set_fields[f"features.{k}"] = bool(v)

    if body.inbound_allowed_guilds is not None:
        try:
            set_fields["inbound_allowed_guilds"] = [int(g) for g in body.inbound_allowed_guilds]
        except ValueError:
            raise HTTPException(status_code=400, detail="inbound_allowed_guilds must contain valid integer snowflakes.")

    if not set_fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    # Who can manage is Manage Server's call, as in the Discord panel and on every other
    # bot: a member who holds only the Manager Role must not hand it to another role or
    # take it away.
    if "manager_role_id" in set_fields and set_fields["manager_role_id"] != (
        str(before["manager_role_id"]) if before.get("manager_role_id") else None
    ):
        if not await has_manage_guild(session, gid):
            raise HTTPException(
                status_code=403,
                detail="Only members with Manage Server can change who can manage the relay.",
            )

    # The Discord panel refuses a log channel the bot cannot post embeds in; so does this.
    # Checked only when the channel changes, and it fails open when Discord cannot answer.
    new_log = set_fields.get("master_log_channel_id")
    if new_log and new_log != str(before.get("master_log_channel_id") or ""):
        perms = await discord_cache.bot_channel_permissions(gid, new_log)
        missing = missing_permissions(perms, LOG_CHANNEL_PERMS)
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"The bot is missing permissions in that log channel: "
                       f"{', '.join(permission_label(m) for m in missing)}. Grant them in the "
                       f"channel's settings, then save again.",
            )

    result = await db.guild_settings().update_one(
        {"guild_id": gid},
        {"$set": set_fields},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Guild configuration not found.")

    # Recorded after the write, and only once it matched, so the history never claims a
    # change that did not happen. The field NAMES are stored, not their values: a log
    # channel or a manager role is a snowflake nobody can read back, and the current
    # value is one click away on the settings page.
    await audit.record(
        session,
        category="settings",
        guild_id=gid,
        action="update_config",
        payload={"fields": sorted(set_fields.keys())},
    )

    return {"ok": True}
