# VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
# Edit the master at EmpireSystems/dashboard_engine/ and run:
#     python EmpireSystems/tools/sync_dashboard_engine.py
# Drift is enforced by:
#     python EmpireSystems/tools/sync_dashboard_engine.py --check
"""Create a role or a channel from a dashboard, through the bot token.

Added 2026-11-20 (TheCodex first). The admin panel already lets an admin create the
role or channel a setting needs right where it is picked (standard section 11,
``admin_engine/admin_cog.py`` inline Create plus
``admin_engine/actions/discord_objects/create.py``). This is the dashboard half of
the same thing, so the two surfaces follow one set of rules:

- The bot must hold the permission Discord requires: Manage Roles to create a role,
  Manage Channels to create a channel, and inside a category Manage Channels and
  View Channel there (a category's overwrites can take them away).
- Names follow the same rules as the panel. A text channel name is lowercase
  letters, digits and "-": capitals are lowered, spaces become "-", "-" runs are
  collapsed, and anything else is refused with the characters named. Voice
  channels, categories and roles are display names: 1 to 100 characters, and a
  role cannot be called everyone or here. ``TestsAndMigrations/EmpireSystems``
  pins these against the admin master so the two cannot drift apart.
- Discord's own limits are checked before asking: 250 roles and 500 channels in a
  server, 50 channels in one category.
- Only kinds a bot can sensibly offer are created: ``text`` (type 0), ``voice``
  (type 2) and ``category`` (type 4). The page decides which of those a given
  setting accepts; this module refuses anything else.

Nothing here saves a setting. A created role or channel comes back in the same
shape the picker lists use, the page selects it, and the person saves the section
as usual. Fail-closed, unlike the read-only cache: when the bot's permissions
cannot be read, creating is not offered.

Usage (in a bot's router)::

    from dashboard._engine import discord_objects as objects

    abilities = await objects.create_abilities(guild_id)
    try:
        role = await objects.create_role(guild_id, "Event Ping", reason="Dashboard: ...")
    except objects.CreateRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

from dashboard._engine.discord_cache import (
    PERMISSION_BITS,
    _api_base,
    _token,
    compute_channel_permissions,
    discord_cache,
)

logger = logging.getLogger("dashboard.discord_objects")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Discord limits (discord.com/developers/docs: guild resource, channel resource).
MAX_GUILD_ROLES = 250
MAX_GUILD_CHANNELS = 500
MAX_CATEGORY_CHANNELS = 50
MAX_NAME_LENGTH = 100
_AUDIT_REASON_MAX = 512

# The kinds a dashboard may create, by Discord channel type.
CHANNEL_KIND_TYPES: Dict[str, int] = {"text": 0, "voice": 2, "category": 4}

# Plain words for the hover text and refusals. The page names the bot.
NEED_MANAGE_ROLES = "needs the Manage Roles permission to create roles"
NEED_MANAGE_CHANNELS = "needs the Manage Channels permission to create channels"
UNREADABLE = "could not check its own permissions in this server right now"


class CreateRefused(Exception):
    """A create that did not happen, with a message a server admin can act on."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# -- Name rules (same as admin_engine/actions/discord_objects/create.py) --------

_RESERVED_ROLE_NAMES = {"everyone", "@everyone", "here", "@here"}
_TEXT_CHANNEL_NAME_RE = re.compile(r"^[a-z0-9-]+$")


def _basic_name(raw: str, what: str) -> Tuple[bool, Optional[str], str]:
    name = (raw or "").strip()
    if not name:
        return False, None, f"{what} name cannot be empty."
    if len(name) > MAX_NAME_LENGTH:
        return False, None, f"{what} name must be {MAX_NAME_LENGTH} characters or fewer."
    return True, name, ""


def validate_role_name(raw: str) -> Tuple[bool, Optional[str], str]:
    """``(ok, name, error)`` - non-empty, <= 100 chars, not a Discord-reserved name."""
    ok, name, error = _basic_name(raw, "Role")
    if not ok:
        return ok, name, error
    if name.lower() in _RESERVED_ROLE_NAMES:
        return False, None, "That name is reserved by Discord. Pick another name."
    return True, name, ""


def validate_channel_name(raw: str) -> Tuple[bool, Optional[str], str]:
    """``(ok, name, error)`` - the fleet rule for TEXT channel names (see module doc)."""
    ok, name, error = _basic_name(raw, "Channel")
    if not ok:
        return ok, name, error
    name = re.sub(r"\s+", "-", name.lower())
    name = re.sub(r"-{2,}", "-", name).strip("-")
    if not name:
        return False, None, "Channel name must include at least one letter or number."
    if not _TEXT_CHANNEL_NAME_RE.fullmatch(name):
        bad = ", ".join(
            f'"{ch}"' for ch in sorted({c for c in name if not _TEXT_CHANNEL_NAME_RE.fullmatch(c)})
        )
        return False, None, (
            'Channel names can only use lowercase letters, numbers, and "-" '
            "(spaces and capitals are converted automatically). "
            f"Remove: {bad}."
        )
    return True, name, ""


def validator_for_channel_kind(kind: str):
    """Text channels get the lowercase/"-" rule; voice channels and categories are
    display names and get the basic check."""
    if kind == "text":
        return validate_channel_name
    return lambda raw: _basic_name(raw, "Category" if kind == "category" else "Channel")


# -- What the bot may create ---------------------------------------------------


def _has(perms: int, name: str) -> bool:
    return bool(perms & PERMISSION_BITS[name])


async def create_abilities(guild_id: str) -> Dict[str, Any]:
    """What the bot can create in this guild right now, for the page's buttons.

    ``{"roles": {"allowed", "reason"}, "channels": {"allowed", "reason"},
    "categories": [{"id", "name", "allowed", "reason"}]}``. ``reason`` is None when
    allowed; otherwise a short phrase the page puts after the bot's name.
    """
    guild_id = str(guild_id)
    perms = await discord_cache.bot_guild_permissions(guild_id)
    if perms is None:
        closed = {"allowed": False, "reason": UNREADABLE}
        return {"roles": dict(closed), "channels": dict(closed), "categories": []}

    roles = await discord_cache.guild_roles_raw(guild_id)
    channels = await discord_cache.guild_channels_raw(guild_id)

    if not _has(perms, "manage_roles"):
        role_ability = {"allowed": False, "reason": NEED_MANAGE_ROLES}
    elif len(roles) >= MAX_GUILD_ROLES:
        role_ability = {
            "allowed": False,
            "reason": f"cannot add a role: this server has reached Discord's limit of {MAX_GUILD_ROLES}",
        }
    else:
        role_ability = {"allowed": True, "reason": None}

    if not _has(perms, "manage_channels"):
        channel_ability = {"allowed": False, "reason": NEED_MANAGE_CHANNELS}
    elif len(channels) >= MAX_GUILD_CHANNELS:
        channel_ability = {
            "allowed": False,
            "reason": f"cannot add a channel: this server has reached Discord's limit of {MAX_GUILD_CHANNELS}",
        }
    else:
        channel_ability = {"allowed": True, "reason": None}

    categories: List[Dict[str, Any]] = []
    member_roles = await discord_cache.bot_member_role_ids(guild_id) or []
    bot_id = await discord_cache.bot_id() or ""
    children: Dict[str, int] = {}
    for ch in channels:
        if ch.get("parent_id"):
            children[str(ch["parent_id"])] = children.get(str(ch["parent_id"]), 0) + 1
    for ch in sorted(
        (c for c in channels if c.get("type") == CHANNEL_KIND_TYPES["category"]),
        key=lambda c: c.get("position", 0),
    ):
        cat_perms = compute_channel_permissions(
            guild_id, roles, bot_id, member_roles, ch.get("permission_overwrites") or [],
        )
        if not (_has(cat_perms, "view_channel") and _has(cat_perms, "manage_channels")):
            entry = {"allowed": False, "reason": "needs View Channel and Manage Channels in this category"}
        elif children.get(str(ch["id"]), 0) >= MAX_CATEGORY_CHANNELS:
            entry = {"allowed": False, "reason": f"this category already holds Discord's limit of {MAX_CATEGORY_CHANNELS} channels"}
        else:
            entry = {"allowed": True, "reason": None}
        categories.append({"id": str(ch["id"]), "name": ch["name"], **entry})

    return {"roles": role_ability, "channels": channel_ability, "categories": categories}


# -- Creating ------------------------------------------------------------------


async def _post(path: str, body: dict, reason: str) -> httpx.Response:
    """One POST with a single 429 retry. Transport failures become a 502 refusal."""
    headers = {
        "Authorization": f"Bot {_token()}",
        "Content-Type": "application/json",
        "X-Audit-Log-Reason": quote((reason or "")[:_AUDIT_REASON_MAX], safe=" "),
    }
    url = f"{_api_base()}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "2"))
                await asyncio.sleep(min(retry_after, 10.0))
                resp = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        logger.warning("Discord POST %s failed to send: %s", path, exc)
        raise CreateRefused("Discord could not be reached. Try again in a moment.", status=502)
    return resp


def _refusal_for(resp: httpx.Response, what: str) -> CreateRefused:
    """Turn a non-2xx Discord answer into a plain refusal."""
    try:
        code = int((resp.json() or {}).get("code") or 0)
    except Exception:
        code = 0
    logger.warning("Discord refused to create a %s: HTTP %s code %s", what, resp.status_code, code)
    if resp.status_code == 403 or code == 50013:
        return CreateRefused(
            f"Discord refused to create the {what}: the bot is missing a permission it needs. "
            "Check the bot's permissions and try again.",
            status=403,
        )
    if code == 30005:
        return CreateRefused(f"This server has reached Discord's limit of {MAX_GUILD_ROLES} roles.", status=409)
    if code == 30013:
        return CreateRefused(f"This server has reached Discord's limit of {MAX_GUILD_CHANNELS} channels.", status=409)
    if resp.status_code == 400:
        return CreateRefused(f"Discord did not accept that {what} name. Try a different one.", status=400)
    return CreateRefused(f"Discord could not create the {what} right now. Try again in a moment.", status=502)


async def create_role(guild_id: str, raw_name: str, *, reason: str) -> Dict[str, Any]:
    """Create a plain role (Discord's defaults, same as the panel). Returns it in the
    role picker's shape. Raises ``CreateRefused``."""
    guild_id = str(guild_id)
    ok, name, error = validate_role_name(raw_name)
    if not ok:
        raise CreateRefused(error)
    abilities = await create_abilities(guild_id)
    if not abilities["roles"]["allowed"]:
        raise CreateRefused(f"The bot {abilities['roles']['reason']}.", status=403)

    resp = await _post(f"/guilds/{guild_id}/roles", {"name": name}, reason)
    if resp.status_code not in (200, 201):
        raise _refusal_for(resp, "role")
    discord_cache.invalidate_guild(guild_id)
    r = resp.json()
    return {
        "id": str(r["id"]),
        "name": r.get("name", name),
        "color": r.get("color", 0),
        "position": r.get("position", 0),
    }


async def create_channel(
    guild_id: str,
    raw_name: str,
    *,
    kind: str,
    parent_id: Optional[str] = None,
    reason: str,
) -> Dict[str, Any]:
    """Create a text channel, voice channel or category. Returns it in the channel
    picker's shape. Raises ``CreateRefused``."""
    guild_id = str(guild_id)
    if kind not in CHANNEL_KIND_TYPES:
        raise CreateRefused("That kind of channel cannot be created here.")
    ok, name, error = validator_for_channel_kind(kind)(raw_name)
    if not ok:
        raise CreateRefused(error)
    if kind == "category" and parent_id:
        raise CreateRefused("A category cannot be placed inside another category.")

    abilities = await create_abilities(guild_id)
    if not abilities["channels"]["allowed"]:
        raise CreateRefused(f"The bot {abilities['channels']['reason']}.", status=403)

    body: Dict[str, Any] = {"name": name, "type": CHANNEL_KIND_TYPES[kind]}
    if parent_id:
        parent_id = str(parent_id)
        category = next((c for c in abilities["categories"] if c["id"] == parent_id), None)
        if category is None:
            raise CreateRefused("That category no longer exists. Pick another or leave it empty.")
        if not category["allowed"]:
            raise CreateRefused(f"The bot {category['reason']}.", status=403)
        body["parent_id"] = parent_id

    resp = await _post(f"/guilds/{guild_id}/channels", body, reason)
    if resp.status_code not in (200, 201):
        raise _refusal_for(resp, "category" if kind == "category" else "channel")
    discord_cache.invalidate_guild(guild_id)
    ch = resp.json()
    return {
        "id": str(ch["id"]),
        "name": ch.get("name", name),
        "type": ch.get("type", CHANNEL_KIND_TYPES[kind]),
        "parent_id": ch.get("parent_id"),
        "position": ch.get("position", 0),
    }
