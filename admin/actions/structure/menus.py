# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Menu structure factory - assemble child nodes into a menu group."""

from __future__ import annotations

from typing import Optional, Callable

from ...views.panel_engine import PanelNode
from ..config import bool_toggle


def menu_group(
    key: str,
    label: str,
    *,
    children: dict[str, PanelNode],
    description: str = "",
    category_group: str = "main",
    toggle_path: Optional[str] = None,
    locked_children: Optional[Callable] = None,
    lock_reason: str = "",
    premium_label: Optional[str] = None,
    mod_allowed: bool = False,
) -> PanelNode:
    """A menu node holding child nodes. ``toggle_path`` wires a feature on/off toggle
    backed by that config bool."""
    toggle_get = toggle_set = None
    if toggle_path is not None:
        toggle_get, toggle_set = bool_toggle(toggle_path)
    return PanelNode(
        key=key, label=label, kind="menu", description=description,
        children=children, category_group=category_group,
        toggle_get=toggle_get, toggle_set=toggle_set,
        locked_children=locked_children, lock_reason=lock_reason,
        premium_label=premium_label, mod_allowed=mod_allowed,
    )
