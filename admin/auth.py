# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""
admin_engine - panel authorization gate (vendored engine module).

Centralizes the role-based access logic every bot shares:

- ``resolve_panel_role_from_config`` - compute a caller's tier ("admin" | "none")
  from manage_guild + the admin role-id list stored in config. A bot's
  ``bindings.resolve_panel_role`` delegates here instead of hand-rolling get_panel_role.
- ``manage_guild_pre_check`` - a reusable ``pre_check`` for the panel-access role-picker node
  so only Manage-Server members can change who has panel access.

Panel access is ADMIN-ONLY fleet-wide: there is no Mod tier, so the resolver returns
either "admin" or "none".

Backend reads go through the bindings seam (``settings/bindings.py``); those imports are lazy
(inside the functions) so ``bindings`` can import this module without a cycle.
"""

from __future__ import annotations


async def resolve_panel_role_from_config(
    user,
    guild_id: int,
    *,
    admin_path: str = "roles.admin_role_ids",
) -> str:
    """Return "admin" | "none" from manage_guild + the configured admin role-id list."""
    perms = getattr(user, "guild_permissions", None)
    if perms is not None and perms.manage_guild:
        return "admin"

    from .settings.bindings import config_get  # lazy: avoid bindings<->auth import cycle

    admin_ids = {int(r) for r in (await config_get(guild_id, admin_path, default=[]) or [])}
    member_ids = {r.id for r in getattr(user, "roles", [])}

    if admin_ids & member_ids:
        return "admin"
    return "none"


async def manage_guild_pre_check(interaction, guild_id: int):
    """pre_check for role-access nodes: allow only members with Manage Server."""
    user = getattr(interaction, "user", None)
    perms = getattr(user, "guild_permissions", None)
    if perms is not None and perms.manage_guild:
        return None
    from .views.base import build_notice_layout
    return build_notice_layout(
        "Manage Server Required",
        "Only members with the **Manage Server** permission can change who has panel access.",
    )
