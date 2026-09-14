"""Forwarding rules CRUD API.

The nested ``settings`` block became editable from the dashboard on 2026-08-13 (owner
ruling): message types, keyword and length filters, formatting and the two advanced
options. Before that the dashboard could only set the four author-filter lists, so
everything else could be changed from the ``/admin`` panel in Discord and nowhere else.

Every settings write is a DOTTED PER-LEAF ``$set`` (``settings.filters.min_length``),
never a replacement of a sub-dict. That matters: ``formatting`` also carries
``max_attachment_size``, ``allowed_attachment_types`` and ``mention_author``, which the
runtime reads and this editor does not expose. Writing the sub-dict whole would silently
erase them from every rule an admin touched here.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_snowflake(v: str | None) -> str | None:
    """Reject non-numeric channel/guild IDs at validation time so a bad value returns
    422, not an uncaught int() ValueError -> 500 in the route handler."""
    if v is not None and not str(v).isdigit():
        raise ValueError("must be a numeric snowflake ID")
    return v

from dashboard import db
from dashboard._engine.discord_cache import discord_cache, missing_permissions, permission_label
from dashboard.auth.dependencies import get_current_user, require_panel_access
from dashboard.routers.dashboard import _fetch_bot_guild_ids
from dashboard.services import audit, rule_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rules"])

# Mirrors the defensive caps in commands/forward/forward.py::check_filters, which
# truncates to 50 keywords of 100 characters at match time. Enforcing the same shape on
# the way in means what is stored is what actually runs - a 60-keyword list would
# otherwise save cleanly and quietly match on only the first 50.
MAX_KEYWORDS = 50
MAX_KEYWORD_LENGTH = 100

# Discord's own message-content ceiling. A max_length above it can never reject anything.
MAX_MESSAGE_LENGTH = 2000

# The one forwarding style implemented today (forward_message always renders the quoted
# native style). Kept as a validated set so a future style is a one-line addition rather
# than an unvalidated free-text field.
FORWARD_STYLES = ("native",)


class AuthorFiltersModel(BaseModel):
    allow_user_ids: list[str] = Field(default_factory=list)
    deny_user_ids: list[str] = Field(default_factory=list)
    allow_role_ids: list[str] = Field(default_factory=list)
    deny_role_ids: list[str] = Field(default_factory=list)


class MessageTypesModel(BaseModel):
    """Which kinds of message a rule copies. All false forwards nothing at all."""

    model_config = ConfigDict(extra="forbid")

    text: bool = True
    media: bool = True
    links: bool = True
    embeds: bool = True
    files: bool = True
    stickers: bool = False


class FiltersModel(BaseModel):
    """Keyword and length gates, applied to the message content before forwarding."""

    model_config = ConfigDict(extra="forbid")

    require_keywords: list[str] = Field(default_factory=list)
    block_keywords: list[str] = Field(default_factory=list)
    min_length: int = Field(default=0, ge=0, le=MAX_MESSAGE_LENGTH)
    max_length: int = Field(default=MAX_MESSAGE_LENGTH, ge=0, le=MAX_MESSAGE_LENGTH)

    @field_validator("require_keywords", "block_keywords")
    @classmethod
    def _clean_keywords(cls, value: list[str]) -> list[str]:
        cleaned = [str(k).strip()[:MAX_KEYWORD_LENGTH] for k in value]
        return [k for k in cleaned if k][:MAX_KEYWORDS]


class FormattingModel(BaseModel):
    """How a forwarded copy is written.

    ``add_prefix`` and ``add_suffix`` ARE applied as of 2026-08-19 (owner ruling):
    ``forward_as_native_style`` wraps them around the quote block, outside it, so they read
    as the rule owner's lines rather than as words the original author wrote. The changelog
    says so, because turning them on changed what appears in every destination channel that
    already had one saved.

    ``forward_style`` is the one that is still STORED but not read - ``forward_message``
    always renders the native style. The editor page says so rather than pretending it
    changes the forwarded message. Do not quietly start honouring it without saying so.
    """

    model_config = ConfigDict(extra="forbid")

    include_author: bool = True
    add_prefix: str = Field(default="", max_length=200)
    add_suffix: str = Field(default="", max_length=200)
    forward_attachments: bool = True
    forward_embeds: bool = True
    forward_style: str = "native"

    @field_validator("forward_style")
    @classmethod
    def _known_style(cls, value: str) -> str:
        if value not in FORWARD_STYLES:
            raise ValueError(f"must be one of: {', '.join(FORWARD_STYLES)}")
        return value


class AdvancedOptionsModel(BaseModel):
    """How keyword matching is performed."""

    model_config = ConfigDict(extra="forbid")

    case_sensitive: bool = False
    whole_word_only: bool = False


class CreateRuleRequest(BaseModel):
    rule_name: str = Field(min_length=1, max_length=100)
    source_channel_id: str
    destination_channel_id: str
    destination_guild_id: str | None = None
    is_active: bool = True
    author_filters: AuthorFiltersModel = Field(default_factory=AuthorFiltersModel)
    # Optional on create: an omitted section keeps rule_service's defaults, which are the
    # same defaults the Discord wizard writes. Only a section the client actually sent is
    # applied, so "create with defaults" stays a one-field request.
    message_types: MessageTypesModel | None = None
    filters: FiltersModel | None = None
    formatting: FormattingModel | None = None
    advanced_options: AdvancedOptionsModel | None = None

    _check_ids = field_validator(
        "source_channel_id", "destination_channel_id", "destination_guild_id"
    )(_validate_snowflake)


class UpdateRuleRequest(BaseModel):
    rule_name: str | None = Field(default=None, min_length=1, max_length=100)
    source_channel_id: str | None = None
    destination_channel_id: str | None = None
    destination_guild_id: str | None = None
    is_active: bool | None = None
    author_filters: AuthorFiltersModel | None = None
    message_types: MessageTypesModel | None = None
    filters: FiltersModel | None = None
    formatting: FormattingModel | None = None
    advanced_options: AdvancedOptionsModel | None = None

    _check_ids = field_validator(
        "source_channel_id", "destination_channel_id", "destination_guild_id"
    )(_validate_snowflake)


#: What the forwarder needs where it watches, and where it posts. The same sets the Discord
#: wizard checks (admin/settings/forwarding_actions.py).
SOURCE_PERMS = ["view_channel", "read_message_history"]
DESTINATION_PERMS = ["send_messages", "attach_files", "embed_links", "read_message_history"]


def _labels(names: list[str]) -> str:
    return ", ".join(permission_label(n) for n in names)


async def _validate_route(
    guild_id: str,
    *,
    source_id: int,
    destination_id: int,
    destination_guild_id: str,
    check_source: bool,
    check_destination: bool,
) -> None:
    """Refuse the routes the Discord wizard refuses.

    The dashboard used to save anything: the same channel twice, a channel the bot cannot
    see or post in, a server that has not allowed this one in. Each saved and then forwarded
    nothing (or collected strikes until it paused itself). Only the parts this save
    changes are checked, and Discord lookups fail open, so an unreachable API never blocks a
    save.
    """
    gid = str(guild_id)
    dgid = str(destination_guild_id)
    cross = dgid != gid

    if not cross and source_id == destination_id:
        raise HTTPException(status_code=400, detail="Source and destination channels must be different.")

    if check_destination and cross:
        bot_guilds = await _fetch_bot_guild_ids()
        if bot_guilds and dgid not in bot_guilds:
            raise HTTPException(
                status_code=422,
                detail="Stygian Relay is not in that destination server, so nothing could be copied there.",
            )
        dest_doc = await db.guild_settings().find_one({"guild_id": dgid}, {"inbound_allowed_guilds": 1})
        allowed = {str(g) for g in ((dest_doc or {}).get("inbound_allowed_guilds") or [])}
        if gid not in allowed:
            raise HTTPException(
                status_code=422,
                detail="That server does not allow inbound forwards from this one. Ask its admins "
                       "to add this server's ID to their cross-server allowlist first.",
            )
        listing = await discord_cache.guild_channels(dgid, types=(0, 5))
        if listing and not any(str(c["id"]) == str(destination_id) for c in listing):
            raise HTTPException(
                status_code=422,
                detail="That destination channel ID is not a text channel in the destination server.",
            )

    if check_source:
        missing = missing_permissions(
            await discord_cache.bot_channel_permissions(gid, str(source_id)), SOURCE_PERMS,
        )
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"The bot is missing permissions in the channel to watch: {_labels(missing)}. "
                       f"It needs View Channel and Read Message History there, or the rule "
                       f"forwards nothing.",
            )

    if check_destination:
        missing = missing_permissions(
            await discord_cache.bot_channel_permissions(dgid, str(destination_id)), DESTINATION_PERMS,
        )
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"The bot is missing permissions in the destination channel: {_labels(missing)}. "
                       f"It needs Send Messages, Attach Files, Embed Links and Read Message "
                       f"History there.",
            )


def _settings_updates(body: CreateRuleRequest | UpdateRuleRequest) -> dict[str, Any]:
    """Dotted per-leaf ``settings.*`` writes for whichever sections were sent.

    Per-leaf rather than per-section so sibling keys the editor does not expose survive
    the write - see the module docstring.
    """
    updates: dict[str, Any] = {}
    for section in ("message_types", "filters", "formatting", "advanced_options"):
        model = getattr(body, section, None)
        if model is None:
            continue
        for key, value in model.model_dump().items():
            updates[f"settings.{section}.{key}"] = value
    return updates


def _validate_lengths(body: CreateRuleRequest | UpdateRuleRequest) -> None:
    """Reject a length window that can never match anything."""
    filters = getattr(body, "filters", None)
    if filters is not None and filters.min_length > filters.max_length:
        raise HTTPException(
            status_code=400,
            detail="Shortest message cannot be longer than the longest message.",
        )


@router.get("/guilds/{guild_id}/rules")
async def list_rules(guild_id: str, session: dict = Depends(get_current_user)):
    await require_panel_access(session, guild_id)
    rules = await rule_service.get_rules(guild_id)
    # No opt-out figure here, by owner ruling 2026-08-19. This used to return
    # `opted_out_members`, a count of accounts that asked relay to skip their messages.
    # It was honest about being account-wide rather than per-server, but it was still a
    # cross-server aggregate on one server's admin page, and it could never be narrowed:
    # `user_preferences` carries no guild dimension, so scoping it would have meant
    # pulling the guild's whole member list from Discord on every page load. Do not
    # reintroduce it without a way to make it about the server being viewed.
    return {"rules": rules, "count": len(rules)}


@router.post("/guilds/{guild_id}/rules", status_code=201)
async def create_rule(
    guild_id: str,
    body: CreateRuleRequest,
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)
    _validate_lengths(body)

    dest_guild = int(body.destination_guild_id) if body.destination_guild_id else None
    await _validate_route(
        guild_id,
        source_id=int(body.source_channel_id),
        destination_id=int(body.destination_channel_id),
        destination_guild_id=str(dest_guild or guild_id),
        check_source=True,
        check_destination=True,
    )

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

    # Any settings sections the client sent are applied on top of the defaults the rule
    # was just created with. Done as a second write rather than folded into create_rule
    # so the active-rule cap stays the single gate on rule creation - a failed settings
    # write leaves a working rule on defaults, not a half-created one.
    settings_updates = _settings_updates(body)
    if settings_updates and rule:
        applied = await rule_service.update_rule(
            guild_id, rule["rule_id"], settings_updates
        )
        if applied == "ok":
            fresh = await rule_service.get_rule(guild_id, rule["rule_id"])
            if fresh is not None:
                rule = fresh
        else:
            logger.warning(
                "Rule %s created but its settings write did not apply", rule["rule_id"]
            )

    await audit.record(
        session,
        category="rules",
        guild_id=str(guild_id),
        action="create_rule",
        payload={
            "rule_id": (rule or {}).get("rule_id", ""),
            "rule_name": body.rule_name,
            "source_channel_id": body.source_channel_id,
            "destination_channel_id": body.destination_channel_id,
            "destination_guild_id": body.destination_guild_id,
            "is_active": body.is_active,
        },
    )

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
    _validate_lengths(body)

    if (
        body.source_channel_id is not None
        or body.destination_channel_id is not None
        or body.destination_guild_id is not None
    ):
        before = await rule_service.get_rule(guild_id, rule_id)
        if before is None:
            raise HTTPException(status_code=404, detail="Rule not found.")
        old_source = str(before.get("source_channel_id") or "")
        old_dest = str(before.get("destination_channel_id") or "")
        old_dest_guild = str(before.get("destination_guild_id") or guild_id)
        new_source = body.source_channel_id or old_source
        new_dest = body.destination_channel_id or old_dest
        # The editor sends no destination server for a same-server rule.
        new_dest_guild = body.destination_guild_id or str(guild_id)
        await _validate_route(
            guild_id,
            source_id=int(new_source),
            destination_id=int(new_dest),
            destination_guild_id=new_dest_guild,
            check_source=new_source != old_source,
            check_destination=(new_dest != old_dest or new_dest_guild != old_dest_guild),
        )

    updates: dict[str, Any] = {}
    if body.rule_name is not None:
        updates["rule_name"] = body.rule_name
    if body.source_channel_id is not None:
        updates["source_channel_id"] = int(body.source_channel_id)
    if body.destination_channel_id is not None:
        updates["destination_channel_id"] = int(body.destination_channel_id)
    if body.destination_guild_id is not None:
        updates["destination_guild_id"] = int(body.destination_guild_id)
    elif body.destination_channel_id is not None:
        # A destination sent without a server is a same-server rule. Without this, a rule
        # switched back from another server kept pointing at that server.
        updates["destination_guild_id"] = int(guild_id)
    if body.is_active is not None:
        updates["is_active"] = body.is_active
    if body.author_filters is not None:
        # The four author-filter lists are written as one sub-dict on purpose: unlike
        # `formatting`, they have no keys beyond the four, and a whole-dict write is what
        # makes removing the last entry from a list actually clear it.
        updates["settings.author_filters"] = body.author_filters.model_dump()

    updates.update(_settings_updates(body))

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    verdict = await rule_service.update_rule(guild_id, rule_id, updates)
    if verdict == "limit_reached":
        raise HTTPException(status_code=429, detail="Active rule limit reached for this guild.")
    if verdict != "ok":
        raise HTTPException(status_code=404, detail="Rule not found or no changes made.")

    # Field names, not values: a payload carrying every keyword and channel id of every
    # edit would make the history unreadable and duplicate data that lives on the rule.
    await audit.record(
        session,
        category="rules",
        guild_id=str(guild_id),
        action="update_rule",
        payload={
            "rule_id": rule_id,
            "rule_name": body.rule_name,
            "fields": sorted(updates.keys()),
        },
    )
    return {"ok": True}


@router.delete("/guilds/{guild_id}/rules/{rule_id}", status_code=204)
async def delete_rule(
    guild_id: str,
    rule_id: str,
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)
    # Read before the delete so the history can name the rule that went. Afterwards there
    # is nothing left to look the name up in, and "deleted rule 7f3a-..." tells nobody
    # anything.
    existing = await rule_service.get_rule(guild_id, rule_id)
    ok = await rule_service.delete_rule(guild_id, rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found.")
    await audit.record(
        session,
        category="rules",
        guild_id=str(guild_id),
        action="delete_rule",
        payload={
            "rule_id": rule_id,
            "rule_name": (existing or {}).get("rule_name", ""),
            "source_channel_id": str((existing or {}).get("source_channel_id") or ""),
            "destination_channel_id": str(
                (existing or {}).get("destination_channel_id") or ""
            ),
        },
    )


@router.patch("/guilds/{guild_id}/rules/{rule_id}/toggle")
async def toggle_rule(
    guild_id: str,
    rule_id: str,
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)
    existing = await rule_service.get_rule(guild_id, rule_id)
    verdict, new_state = await rule_service.toggle_rule(guild_id, rule_id)
    if verdict == "limit_reached":
        raise HTTPException(status_code=429, detail="Active rule limit reached for this guild.")
    if verdict != "ok" or new_state is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    await audit.record(
        session,
        category="rules",
        guild_id=str(guild_id),
        action="resume_rule" if new_state else "pause_rule",
        payload={
            "rule_id": rule_id,
            "rule_name": (existing or {}).get("rule_name", ""),
            "is_active": new_state,
        },
    )
    return {"is_active": new_state}
