# ───────────────────────────────────────────────────────────────────────────
# VENDORED from admin_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Structure actions: menu grouping + confirm-gated / info / modal / member action factories."""

from .menus import menu_group
from .confirm import confirm_action, purge_action
from .info import info_action
from .modals import modal_action
from .members import member_action
from .scoped import scoped_guild_action, scoped_member_action

__all__ = [
    "menu_group", "confirm_action", "purge_action",
    "info_action", "modal_action", "member_action",
    "scoped_guild_action", "scoped_member_action",
]
