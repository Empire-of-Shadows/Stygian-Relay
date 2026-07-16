# ───────────────────────────────────────────────────────────────────────────
# VENDORED from admin_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""
admin_engine — panel authorization gate (vendored engine module).

Centralizes the role-based access logic every bot shares:

- ``resolve_panel_role_from_config`` — compute a caller's tier ("admin" | "mod" | "none")
  from manage_guild + the admin/mod role-id lists stored in config. A bot's
  ``bindings.resolve_panel_role`` delegates here instead of hand-rolling get_panel_role.
- ``manage_guild_pre_check`` — a reusable ``pre_check`` for the admin/mod role-picker nodes
  so only Manage-Server members can change who has panel access.
- ``effective_mod_allowed`` — resolve a node's mod access from the declarative ``mod_allowed``
  flags in the panel tree (a menu's ``True`` cascades to children; a child's ``False`` overrides).

Backend reads go through the bindings seam (``settings/bindings.py``); those imports are lazy
(inside the functions) so ``bindings`` can import this module without a cycle.
"""

from __future__ import annotations

from typing import Optional


async def resolve_panel_role_from_config(
    user,
    guild_id: int,
    *,
    admin_path: str = "roles.admin_role_ids",
    mod_path: str = "roles.mod_role_ids",
) -> str:
    """Return "admin" | "mod" | "none" from manage_guild + configured role-id lists."""
    perms = getattr(user, "guild_permissions", None)
    if perms is not None and perms.manage_guild:
        return "admin"

    from .settings.bindings import config_get  # lazy: avoid bindings<->auth import cycle

    admin_ids = {int(r) for r in (await config_get(guild_id, admin_path, default=[]) or [])}
    mod_ids = {int(r) for r in (await config_get(guild_id, mod_path, default=[]) or [])}
    member_ids = {r.id for r in getattr(user, "roles", [])}

    if admin_ids & member_ids:
        return "admin"
    if mod_ids & member_ids:
        return "mod"
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


def effective_mod_allowed(root, node) -> bool:
    """Resolve ``node``'s effective mod access within the ``root`` panel tree.

    A node's ``mod_allowed`` is tri-state: ``True``/``False`` are explicit; ``None`` inherits
    from the nearest ancestor that set it (root default: False, i.e. admin-only). For a
    top-level category (direct child of root) whose value is ``None``, fall back to legacy
    ``MOD_ALLOWED_CATEGORIES`` membership so not-yet-retrofitted panels keep working; that
    result then cascades to its descendants.
    """
    try:
        from .settings.bindings import MOD_ALLOWED_CATEGORIES  # legacy fallback (optional)
    except Exception:
        MOD_ALLOWED_CATEGORIES = frozenset()

    def _walk(cur, inherited: bool, depth: int) -> Optional[bool]:
        own = getattr(cur, "mod_allowed", None)
        if own is not None:
            eff = bool(own)
        elif depth == 1 and cur.key in MOD_ALLOWED_CATEGORIES:
            eff = True
        else:
            eff = inherited

        if cur is node:
            return eff
        for child in (cur.children or {}).values():
            found = _walk(child, eff, depth + 1)
            if found is not None:
                return found
        return None

    result = _walk(root, False, 0)
    return bool(result) if result is not None else False
