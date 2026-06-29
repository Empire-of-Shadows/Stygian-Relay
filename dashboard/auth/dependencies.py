"""FastAPI dependencies for authentication."""

from fastapi import Cookie, HTTPException

from dashboard.auth.session import get_session, refresh_guilds_if_stale
from dashboard.auth.signing import unsign_token
from dashboard.auth.panel_role import PanelRole, has_manage_guild, resolve_panel_role
from dashboard.config import MANAGE_GUILD_PERMISSION, SESSION_COOKIE_NAME


async def get_current_user(
    eos_session: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> dict:
    if not eos_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    raw_token = unsign_token(eos_session)
    if raw_token is None:
        raise HTTPException(status_code=401, detail="Invalid session signature")
    session = await get_session(raw_token)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired")
    session = await refresh_guilds_if_stale(session)
    return session


def user_can_manage_guild(session: dict, guild_id: str) -> bool:
    """MANAGE_GUILD from the OAuth login snapshot (display hint only)."""
    for guild in session.get("guilds", []):
        if str(guild["id"]) == str(guild_id):
            perms = int(guild.get("permissions", 0))
            return (perms & MANAGE_GUILD_PERMISSION) == MANAGE_GUILD_PERMISSION
    return False


async def require_guild_access(session: dict, guild_id: str):
    """Require live MANAGE_GUILD for this guild."""
    if not await has_manage_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="No MANAGE_GUILD permission for this guild")


async def require_panel_access(session: dict, guild_id: str) -> PanelRole:
    """Resolve and require Admin tier panel access for this guild.

    Relay has no mod tier — returns "admin" or raises 403.
    """
    role = await resolve_panel_role(session, guild_id)
    if role == "none":
        raise HTTPException(status_code=403, detail="No panel access for this guild")
    return role
