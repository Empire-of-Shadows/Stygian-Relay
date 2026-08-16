# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Feature builder: the panel-access role list.

Generalizes the admin role picker the list-schema bots hand-roll (TheCodex, TheHost,
The Decree): a ``role_select`` list of who gets admin panel access, wired to the canonical
``GuildConfig`` role path and gated so only Manage-Server members can change who has panel
access. It is the role analogue of ``access_list_pair`` for channels; both are thin
wrappers over the config-bound leaf factories in ``actions/config/leaves.py``.

Panel access is ADMIN-ONLY fleet-wide - there is no Mod tier - so the factory builds a
single node. It still returns a dict so a bot indexes the node by its own key::

    from admin_engine.actions.features import panel_roles_pair
    nodes = panel_roles_pair()
    PANEL_ACCESS = menu_group("panel_access", "Panel Access",
                              children=[nodes["admin_roles"]])

The closures read/write through the config seam (``config_get`` / ``config_set``), so a bot
only needs its ``bindings.config_*`` doers to reach that path; no per-bot get/set/clear
helpers. (Relay is intentionally NOT an adopter: it uses a single ``manager_role_id``, so
its single-role picker is not this role-list pattern.)
"""

from __future__ import annotations

from typing import Callable, Optional

from ..config.leaves import role_leaf
from ...auth import manage_guild_pre_check
from ...permission_checks import check_delegation_role
from ...views.panel_engine import PanelNode


async def _delegation_validator(guild, values) -> Optional[str]:
    """Reject @everyone / managed / deleted roles for access lists.

    Deliberately no hierarchy check: panel access is delegation, not assignment -
    admin roles normally sit above the bot and must stay selectable."""
    for rid in values:
        ok, err = check_delegation_role(guild, int(rid))
        if not ok:
            return err
    return None


def panel_roles_pair(
    *,
    admin_key: str = "admin_roles",
    admin_path: str = "roles.admin_role_ids",
    admin_label: str = "Panel Access Roles",
    admin_description: str = (
        "Grants full admin panel access (same as Manage Server) to members "
        "holding any of these roles."
    ),
    max_values: int = 10,
    pre_check: Optional[Callable] = manage_guild_pre_check,
    str_ids: bool = False,
) -> dict[str, PanelNode]:
    """Return ``{admin_key: node}``, the panel-access role list.

    The node is a multi ``role_select`` list wired to ``admin_path`` (the canonical
    ``roles.admin_role_ids``) and gated by ``pre_check`` (by default
    ``auth.manage_guild_pre_check``, so only members with Manage Server can change who has panel
    access). Pass ``pre_check=None`` to drop that gate, or ``str_ids=True`` to store ids as
    strings (e.g. EcomRebuild).

    Selections are validated with ``check_delegation_role``: @everyone, integration-managed,
    and deleted roles are rejected. The bot-hierarchy rule is deliberately NOT applied -
    these roles are only checked for membership, never assigned, and admin roles normally
    sit above the bot.
    """
    return {
        admin_key: role_leaf(
            admin_key, admin_path, label=admin_label, description=admin_description,
            multi=True, max_values=max_values, pre_check=pre_check, str_ids=str_ids,
            value_validator=_delegation_validator,
        ),
    }
