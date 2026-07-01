"""Forwarding rules CRUD API."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from dashboard.auth.dependencies import get_current_user, require_panel_access
from dashboard.services import rule_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rules"])


class AuthorFiltersModel(BaseModel):
    allow_user_ids: list[str] = Field(default_factory=list)
    deny_user_ids: list[str] = Field(default_factory=list)
    allow_role_ids: list[str] = Field(default_factory=list)
    deny_role_ids: list[str] = Field(default_factory=list)


class CreateRuleRequest(BaseModel):
    rule_name: str = Field(min_length=1, max_length=100)
    source_channel_id: str
    destination_channel_id: str
    destination_guild_id: str | None = None
    is_active: bool = True
    author_filters: AuthorFiltersModel = Field(default_factory=AuthorFiltersModel)


class UpdateRuleRequest(BaseModel):
    rule_name: str | None = Field(default=None, min_length=1, max_length=100)
    source_channel_id: str | None = None
    destination_channel_id: str | None = None
    destination_guild_id: str | None = None
    is_active: bool | None = None
    author_filters: AuthorFiltersModel | None = None


@router.get("/guilds/{guild_id}/rules")
async def list_rules(guild_id: str, session: dict = Depends(get_current_user)):
    await require_panel_access(session, guild_id)
    rules = await rule_service.get_rules(guild_id)
    return {"rules": rules, "count": len(rules)}


@router.post("/guilds/{guild_id}/rules", status_code=201)
async def create_rule(
    guild_id: str,
    body: CreateRuleRequest,
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)

    dest_guild = int(body.destination_guild_id) if body.destination_guild_id else None

    ok, reason, rule = await rule_service.create_rule(
        guild_id,
        rule_name=body.rule_name,
        source_channel_id=int(body.source_channel_id),
        destination_channel_id=int(body.destination_channel_id),
        destination_guild_id=dest_guild,
        author_filters=body.author_filters.model_dump(),
        is_active=body.is_active,
    )

    if not ok:
        if reason == "limit_reached":
            raise HTTPException(status_code=429, detail="Active rule limit reached for this guild.")
        if reason == "guild_not_found":
            raise HTTPException(status_code=404, detail="Guild configuration not found.")
        raise HTTPException(status_code=500, detail="Failed to create rule.")

    return rule


@router.get("/guilds/{guild_id}/rules/{rule_id}")
async def get_rule(guild_id: str, rule_id: str, session: dict = Depends(get_current_user)):
    await require_panel_access(session, guild_id)
    rule = await rule_service.get_rule(guild_id, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return rule


@router.put("/guilds/{guild_id}/rules/{rule_id}")
async def update_rule(
    guild_id: str,
    rule_id: str,
    body: UpdateRuleRequest,
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)

    updates: dict[str, Any] = {}
    if body.rule_name is not None:
        updates["rule_name"] = body.rule_name
    if body.source_channel_id is not None:
        updates["source_channel_id"] = int(body.source_channel_id)
    if body.destination_channel_id is not None:
        updates["destination_channel_id"] = int(body.destination_channel_id)
    if body.destination_guild_id is not None:
        updates["destination_guild_id"] = int(body.destination_guild_id)
    if body.is_active is not None:
        updates["is_active"] = body.is_active
    if body.author_filters is not None:
        updates["settings.author_filters"] = body.author_filters.model_dump()

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    ok = await rule_service.update_rule(guild_id, rule_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found or no changes made.")
    return {"ok": True}


@router.delete("/guilds/{guild_id}/rules/{rule_id}", status_code=204)
async def delete_rule(
    guild_id: str,
    rule_id: str,
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)
    ok = await rule_service.delete_rule(guild_id, rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found.")


@router.patch("/guilds/{guild_id}/rules/{rule_id}/toggle")
async def toggle_rule(
    guild_id: str,
    rule_id: str,
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)
    new_state = await rule_service.toggle_rule(guild_id, rule_id)
    if new_state is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return {"is_active": new_state}
