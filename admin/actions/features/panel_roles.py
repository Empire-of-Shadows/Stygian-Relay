# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Feature builder: the admin/mod panel-access role pair.

Generalizes the admin/mod role pickers the list-schema bots hand-roll (TheCodex, TheHost,
The Decree): two ``role_select`` lists (who gets full admin panel access, and who gets
mod-tier access), wired to the canonical ``GuildConfig`` role paths and gated so only
Manage-Server members can change who has panel access. It is the role analogue of
``access_list_pair`` for channels; both are thin wrappers over the config-bound leaf
factories in ``actions/config/leaves.py``.

A bot drops the returned nodes into its "Panel Access" menu::

    from admin_engine.actions.features import panel_roles_pair
    nodes = panel_roles_pair()
    PANEL_ACCESS = menu_group("panel_access", "Panel Access",
                              children=[nodes["admin_roles"], nodes["mod_roles"]])

The closures read/write through the config seam (``config_get`` / ``config_set``), so a bot
only needs its ``bindings.config_*`` doers to reach those paths; no per-bot get/set/clear
helpers. (Relay is intentionally NOT an adopter: it uses a single ``manager_role_id``,
admin-only, so its single-role picker is not this admin/mod-list pattern.)
"""

from __future__ import annotations

from typing import Callable, Optional

from ..config.leaves import role_leaf
from ...auth import manage_guild_pre_check
from ...views.panel_engine import PanelNode


def panel_roles_pair(
    *,
    admin_key: str = "admin_roles",
    mod_key: str = "mod_roles",
    admin_path: str = "roles.admin_role_ids",
    mod_path: str = "roles.mod_role_ids",
    admin_label: str = "Panel Access Roles",
    mod_label: str = "Mod Access Roles",
    admin_description: str = (
        "Grants full admin panel access (same as Manage Server). Members holding any of "
        "these roles can open the admin panel."
    ),
    mod_description: str = (
        "Optional. Grants limited (mod-tier) panel access to the sections your admins opt "
        "in. Leave blank to disable the Mod tier."
    ),
    max_values: int = 10,
    include_mod: bool = True,
    pre_check: Optional[Callable] = manage_guild_pre_check,
    str_ids: bool = False,
) -> dict[str, PanelNode]:
    """Return ``{admin_key: node[, mod_key: node]}``, the panel-access role lists.

    Both are multi ``role_select`` lists wired to ``admin_path`` / ``mod_path`` (the canonical
    ``roles.admin_role_ids`` / ``roles.mod_role_ids``) and gated by ``pre_check`` (by default
    ``auth.manage_guild_pre_check``, so only members with Manage Server can change who has panel
    access). Pass ``pre_check=None`` to drop that gate, ``include_mod=False`` for an admin-only
    bot, or ``str_ids=True`` to store ids as strings (e.g. EcomRebuild).
    """
    nodes: dict[str, PanelNode] = {
        admin_key: role_leaf(
            admin_key, admin_path, label=admin_label, description=admin_description,
            multi=True, max_values=max_values, pre_check=pre_check, str_ids=str_ids,
        ),
    }
    if include_mod:
        nodes[mod_key] = role_leaf(
            mod_key, mod_path, label=mod_label, description=mod_description,
            multi=True, max_values=max_values, pre_check=pre_check, str_ids=str_ids,
        )
    return nodes
