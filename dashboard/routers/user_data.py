"""User-scoped API: the member's own privacy choices, export, erasure, and relay view.

Every route here is gated on ``get_current_user`` ONLY - never ``require_panel_access``.
That is the point of the file: these are a member's own data and a member's own view of
where their messages go, and an ordinary member with no permissions in any server must be
able to reach all of it. Guild-scoped routes additionally check that the caller is a
member of the guild they named, from the session's guild snapshot.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from dashboard.auth.dependencies import get_current_user
# Private-by-name but same-package: the bot's guild-id set is fetched and cached once in
# the dashboard router, and a second copy here would double the Discord calls.
from dashboard.routers.dashboard import _fetch_bot_guild_ids
from dashboard.services import relay_view, user_data

router = APIRouter(tags=["user-data"])


def _resolve_scope(session: dict, guild_id: str | None) -> str | None:
    """Validate an optional guild_id against session membership. Returns str or None."""
    if not guild_id:
        return None
    if not str(guild_id).isdigit():
        raise HTTPException(status_code=400, detail="Invalid guild_id")
    member = any(str(g.get("id")) == str(guild_id) for g in session.get("guilds", []))
    if not member:
        raise HTTPException(
            status_code=404,
            detail="You are not a member of this server (or your session is out of date).",
        )
    return str(guild_id)


# ── Privacy choices ──────────────────────────────────────────────────────────


class PrivacyFeatures(BaseModel):
    """The member's privacy choices. Unknown keys are rejected.

    A ``True`` value means OPTED OUT of that thing, matching the bot-side flag polarity
    in ``storage/settings/user_preferences.py``.
    """

    model_config = ConfigDict(extra="forbid")

    all: bool = False
    relay_messages: bool = False
    show_name: bool = False


@router.get("/user/privacy", summary="The signed-in member's relay privacy choices")
async def get_privacy(session: dict = Depends(get_current_user)):
    """Read the member's two privacy choices.

    Both default to false when nothing has ever been saved, so a first visit returns a
    complete answer rather than a 404.
    """
    user_id = str(session["user_data"]["id"])
    return {"features": await user_data.get_privacy(user_id)}


@router.put("/user/privacy", summary="Save the signed-in member's relay privacy choices")
async def put_privacy(
    features: PrivacyFeatures = Body(..., embed=True),
    session: dict = Depends(get_current_user),
):
    """Save the member's choices and return what was stored.

    The body is the same envelope the GET returns - ``{"features": {...}}`` - so a client
    can round-trip what it just read.

    Account-wide and forward-only: the choices apply in every server relay runs in, and
    they never delete anything. The bot picks them up within about a minute (its
    preference cache TTL). Use DELETE /user/data for erasure.
    """
    user_id = str(session["user_data"]["id"])
    saved = await user_data.set_privacy(user_id, features.model_dump())
    return {"features": saved}


# ── Scope, export, delete ────────────────────────────────────────────────────


@router.get("/user/data/guilds", summary="Servers where relay holds something of yours")
async def user_data_guilds(session: dict = Depends(get_current_user)):
    """Servers relay holds member data for, for the privacy page's scope picker."""
    user_id = str(session["user_data"]["id"])
    ids = await user_data.distinct_guild_ids(user_id)
    name_map = {str(g["id"]): g for g in session.get("guilds", [])}
    return [
        {
            "id": gid,
            "name": name_map.get(gid, {}).get("name"),
            "icon": name_map.get(gid, {}).get("icon"),
        }
        for gid in sorted(ids)
    ]


@router.get("/user/data/export", summary="Download everything relay stores about you")
async def export_data(
    guild_id: str | None = Query(None),
    session: dict = Depends(get_current_user),
):
    """Download the member's relay data as a JSON attachment, optionally one server only.

    Deliberately small: relay stores almost nothing about an individual. The file holds
    the audit entries where the member was the actor, the rules whose author filters name
    them, their premium entitlement rows, and their own privacy choices - and a ``notes``
    block explaining why there is nothing else, so the download is not mistaken for a
    broken export.
    """
    user_id = str(session["user_data"]["id"])
    gid = _resolve_scope(session, guild_id)
    payload = await user_data.export_all(user_id, gid)
    body = json.dumps(payload, indent=2, default=str).encode("utf-8")

    suffix = f"-server-{gid}" if gid is not None else ""
    filename = f"stygian-relay-data-{user_id}{suffix}.json"
    return StreamingResponse(
        iter([body]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class DeleteRequest(BaseModel):
    confirm: bool = False
    guild_id: str | None = None


@router.delete("/user/data", summary="Erase your data from relay's rules")
async def delete_data(
    body: DeleteRequest,
    session: dict = Depends(get_current_user),
):
    """Erase the member's id from relay's forwarding rules, optionally one server only.

    Must be confirmed by sending ``{confirm: true}``.

    Full erasure (owner ruling 2026-08-13): the member's id is removed from every rule's
    allow and deny author-filter lists in scope. This CHANGES WHAT THE SERVER RELAYS - a
    deny entry that was keeping their messages out goes with it, as does an allow entry
    that was the only thing letting them through.

    Kept on purpose: audit entries (a server keeps a complete record of who changed
    what), the member's privacy choices (an erasure must never switch relaying back on),
    and premium entitlements (a purchase record). Copies already posted into a Discord
    channel cannot be deleted by relay at all.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Delete must be confirmed by sending {confirm: true}.",
        )
    user_id = str(session["user_data"]["id"])
    gid = _resolve_scope(session, body.guild_id)
    deleted = await user_data.delete_all(user_id, gid)
    return {"user_id": user_id, "guild_id": gid, "deleted": deleted}


# ── The member's relay view ──────────────────────────────────────────────────


@router.get("/user/relay-view", summary="Where your messages go, per server")
async def relay_view_endpoint(
    guild: str | None = Query(None),
    session: dict = Depends(get_current_user),
):
    """Active routes in the member's servers, and which of them carry their messages.

    Gated on session membership rather than panel access, on purpose: this is a member's
    own answer to "where do my messages go", and it returns only what a member is
    entitled to - active routes, channel names resolved server-side, the destination
    server's name when a route leaves, and a yes/no about the caller themselves. It never
    returns the channel listing, the filter lists, or anything about another member.
    """
    user_id = str(session["user_data"]["id"])
    session_guilds = session.get("guilds", [])
    names = {str(g["id"]): g.get("name") for g in session_guilds}

    if guild is not None:
        gid = _resolve_scope(session, guild)
        candidates = [gid] if gid else []
    else:
        candidates = [str(g["id"]) for g in session_guilds]

    bot_guild_ids = await _fetch_bot_guild_ids()
    shared = [gid for gid in candidates if gid in bot_guild_ids]

    return await relay_view.build_member_view(user_id, shared, names)
