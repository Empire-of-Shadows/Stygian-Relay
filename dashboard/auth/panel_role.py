"""Panel-role policy for the Relay dashboard (2-tier: admin / none).

The live guild-permission plumbing (bot-token MANAGE_GUILD check, member-role fetch, rate
limiter, caches) lives in the shared engine at ``dashboard/_engine/auth/panel_access.py``.
This file is only relay's tier policy. Mirrors ``admin/settings/bindings.py::resolve_panel_role``.
"""

from __future__ import annotations

from dashboard import db
from dashboard._engine.auth.panel_access import (
    PanelRole,
    has_manage_guild,
    member_role_ids,
    session_has_manage_guild,
)

# Relay has no mod tier - this frozenset is intentionally empty.
MOD_ALLOWED_SECTIONS: frozenset[str] = frozenset()


async def _guild_panel_roles(guild_id: str) -> tuple[list[int], list[int]]:
    """Return (admin_role_ids, mod_role_ids) for `guild_id`.

    Relay uses a single `manager_role_id` field (no mod tier).
    """
    doc = await db.guild_settings().find_one(
        {"guild_id": str(guild_id)}, projection={"manager_role_id": 1}
    )
    if not doc:
        return ([], [])
    raw = doc.get("manager_role_id")
    if not raw:
        return ([], [])
    try:
        mid = int(raw)
    except (TypeError, ValueError):
        return ([], [])
    return ([mid], [])


async def resolve_panel_role(
    session: dict, guild_id: str, *, verify_manage_live: bool = True
) -> PanelRole:
    """Resolve the user's panel access tier for `guild_id`.

    Precedence (mirrors bindings.py::resolve_panel_role):
      1. MANAGE_GUILD permission -> "admin"
      2. Configured manager_role_id -> "admin"
      3. Otherwise -> "none"

    ``verify_manage_live=False`` uses the cheap session snapshot for the MANAGE_GUILD step
    (for guild-list probing); the default verifies it live via the bot token.
    """
    if verify_manage_live:
        if await has_manage_guild(session, guild_id):
            return "admin"
    elif session_has_manage_guild(session, guild_id):
        return "admin"

    admin_role_ids, _ = await _guild_panel_roles(guild_id)
    if not admin_role_ids:
        return "none"

    user_id = session.get("user_id") or session.get("user_data", {}).get("id")
    if not user_id:
        return "none"

    member_roles = await member_role_ids(str(guild_id), str(user_id))
    if not member_roles:
        return "none"

    admin_role_str = {str(r) for r in admin_role_ids}
    if admin_role_str & set(member_roles):
        return "admin"
    return "none"
