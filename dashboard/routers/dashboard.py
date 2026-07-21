"""Dashboard API routes - user info, guilds, channels, roles, bot invite."""

import asyncio
import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException

from dashboard import db
from dashboard.auth.dependencies import (
    get_current_user,
    require_panel_access,
)
from dashboard.auth.panel_role import resolve_panel_role
from dashboard.config import BOT_TOKEN, DISCORD_API_BASE, MANAGE_GUILD_PERMISSION

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

_CACHE_TTL = 300
_RESOURCE_CACHE_TTL = 60

_bot_guilds_cache: dict[str, object] = {"ids": set(), "ts": 0.0}
_bot_id_cache: dict[str, object] = {"id": None, "ts": 0.0}
_channels_cache: dict[str, dict] = {}
_roles_cache: dict[str, dict] = {}

_ADMIN_PROBE_LIMIT = 25


@router.get("/me")
async def me(session: dict = Depends(get_current_user)):
    user = session["user_data"]
    can_manage_any = any(
        (int(g.get("permissions", 0)) & MANAGE_GUILD_PERMISSION) == MANAGE_GUILD_PERMISSION
        for g in session.get("guilds", [])
    )

    bot_guild_ids = await _fetch_bot_guild_ids()
    candidate_ids = [
        g["id"] for g in session.get("guilds", [])
        if g["id"] in bot_guild_ids
    ][:_ADMIN_PROBE_LIMIT]
    results = await asyncio.gather(
        *(resolve_panel_role(session, gid, verify_manage_live=False) for gid in candidate_ids),
        return_exceptions=True,
    )
    roles = [r for r in results if isinstance(r, str)]
    can_access_admin_any = can_manage_any or any(r == "admin" for r in roles)

    return {
        "id": user["id"],
        "username": user.get("username"),
        "global_name": user.get("global_name"),
        "avatar": user.get("avatar"),
        "discriminator": user.get("discriminator"),
        "can_manage_any": can_manage_any,
        "can_access_admin_any": can_access_admin_any,
        "can_access_mod_any": False,  # relay has no mod tier
        "can_access_settings_any": can_access_admin_any,
    }


async def _fetch_bot_guild_ids() -> set[str]:
    if not BOT_TOKEN:
        return set()
    now = time.monotonic()
    if _bot_guilds_cache["ids"] and now - _bot_guilds_cache["ts"] < _CACHE_TTL:
        return _bot_guilds_cache["ids"]

    guild_ids: set[str] = set()
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    after = "0"
    async with httpx.AsyncClient() as client:
        while True:
            url = f"{DISCORD_API_BASE}/users/@me/guilds?limit=200&after={after}"
            resp = await client.get(url, headers=headers)
            if resp.status_code == 429:
                await asyncio.sleep(float(resp.headers.get("Retry-After", "2")))
                resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning("Failed to fetch bot guilds: %s", resp.status_code)
                return _bot_guilds_cache["ids"] or guild_ids
            guilds = resp.json()
            if not guilds:
                break
            for g in guilds:
                guild_ids.add(g["id"])
            if len(guilds) < 200:
                break
            after = guilds[-1]["id"]

    _bot_guilds_cache["ids"] = guild_ids
    _bot_guilds_cache["ts"] = now
    return guild_ids


async def _guild_ids_with_config(guild_ids: list[str]) -> set[str]:
    """Return the subset of guild_ids that have a guild_settings document."""
    if not guild_ids:
        return set()
    cursor = db.guild_settings().find(
        {"guild_id": {"$in": list(guild_ids)}},
        {"guild_id": 1},
    )
    return {doc["guild_id"] async for doc in cursor}


@router.get("/guilds")
async def guilds(session: dict = Depends(get_current_user)):
    session_guilds = session.get("guilds", [])
    if not session_guilds:
        return []

    candidate_ids = [g["id"] for g in session_guilds]
    bot_guild_ids, configured_ids = await asyncio.gather(
        _fetch_bot_guild_ids(),
        _guild_ids_with_config(candidate_ids),
    )

    probe_targets = [gid for gid in candidate_ids if gid in bot_guild_ids]
    role_results = await asyncio.gather(
        *(resolve_panel_role(session, gid, verify_manage_live=False) for gid in probe_targets),
        return_exceptions=True,
    )
    panel_roles = {
        gid: (r if isinstance(r, str) else "none")
        for gid, r in zip(probe_targets, role_results)
    }

    out: list[dict] = []
    for guild in session_guilds:
        gid = guild["id"]
        perms = int(guild.get("permissions", 0))
        has_manage = (perms & MANAGE_GUILD_PERMISSION) == MANAGE_GUILD_PERMISSION
        panel_role = panel_roles.get(gid, "none")
        if not has_manage and panel_role == "none":
            continue
        out.append({
            "id": gid,
            "name": guild["name"],
            "icon": guild.get("icon"),
            "bot_in_guild": gid in bot_guild_ids,
            "has_config": gid in configured_ids,
            "setup_required": gid not in bot_guild_ids,
            "panel_role": panel_role if panel_role != "none" else (
                "admin" if has_manage else "none"
            ),
        })
    return out


@router.get("/bot-invite-url")
async def bot_invite_url():
    if not BOT_TOKEN:
        return {"url": None}
    now = time.monotonic()
    if _bot_id_cache["id"] and now - _bot_id_cache["ts"] < _CACHE_TTL:
        bot_id = _bot_id_cache["id"]
    else:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bot {BOT_TOKEN}"}
            resp = await client.get(f"{DISCORD_API_BASE}/users/@me", headers=headers)
            if resp.status_code != 200:
                return {"url": None}
            bot_id = resp.json()["id"]
            _bot_id_cache["id"] = bot_id
            _bot_id_cache["ts"] = now

    # Permissions: view_channels + send_messages + read_message_history +
    # embed_links + attach_files + manage_webhooks
    permissions = 1024 | 2048 | 65536 | 16384 | 32768 | 536870912
    url = (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={bot_id}"
        f"&permissions={permissions}"
        f"&scope=bot%20applications.commands"
    )
    return {"url": url}


@router.get("/guilds/{guild_id}/channels")
async def guild_channels(guild_id: str, session: dict = Depends(get_current_user)):
    await require_panel_access(session, guild_id)
    now = time.monotonic()
    cached = _channels_cache.get(guild_id)
    if cached and now - cached["ts"] < _RESOURCE_CACHE_TTL:
        return cached["data"]

    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{DISCORD_API_BASE}/guilds/{guild_id}/channels", headers=headers)
        if resp.status_code == 429:
            await asyncio.sleep(float(resp.headers.get("Retry-After", "2")))
            resp = await client.get(f"{DISCORD_API_BASE}/guilds/{guild_id}/channels", headers=headers)
        if resp.status_code != 200:
            logger.warning("Failed to fetch channels for %s: %s", guild_id, resp.status_code)
            return []

    raw = resp.json()
    channels = [
        {"id": c["id"], "name": c["name"], "type": c["type"], "parent_id": c.get("parent_id"),
         "position": c.get("position", 0)}
        for c in raw if c["type"] in (0, 4, 5)
    ]
    channels.sort(key=lambda c: (c["type"] != 4, c["position"]))
    _channels_cache[guild_id] = {"data": channels, "ts": now}
    return channels


@router.get("/guilds/{guild_id}/roles")
async def guild_roles(guild_id: str, session: dict = Depends(get_current_user)):
    await require_panel_access(session, guild_id)
    now = time.monotonic()
    cached = _roles_cache.get(guild_id)
    if cached and now - cached["ts"] < _RESOURCE_CACHE_TTL:
        return cached["data"]

    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{DISCORD_API_BASE}/guilds/{guild_id}/roles", headers=headers)
        if resp.status_code == 429:
            await asyncio.sleep(float(resp.headers.get("Retry-After", "2")))
            resp = await client.get(f"{DISCORD_API_BASE}/guilds/{guild_id}/roles", headers=headers)
        if resp.status_code != 200:
            return []

    roles = [
        {"id": r["id"], "name": r["name"], "color": r.get("color", 0), "position": r.get("position", 0)}
        for r in resp.json()
        if r.get("position", 0) > 0 and not r.get("managed", False)
    ]
    roles.sort(key=lambda r: -r["position"])
    _roles_cache[guild_id] = {"data": roles, "ts": now}
    return roles
