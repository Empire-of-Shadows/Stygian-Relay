# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Collection-bound node factory — browse a Mongo collection with a per-item action."""

from __future__ import annotations

from typing import Optional, Callable

from ...views.panel_engine import PanelNode
from .documents import list_documents, count_documents, delete_document


def paginated_list_node(
    key, *, collection, label, line_formatter, value_getter, option_label,
    description="", action_label="Delete", id_field="_id", page_size=10,
    query: Optional[Callable] = None, delete_query: Optional[Callable] = None,
    confirm_line: Optional[Callable] = None, mod_allowed=False, premium_label=None,
) -> PanelNode:
    """A paginated_list node browsing ``collection`` with a per-item action (default delete).

    ``query(guild_id) -> dict`` selects the documents (default ``{"guild_id": guild_id}``).
    ``delete_query(guild_id, value) -> dict`` selects the doc to delete (default
    ``{**query, id_field: value}``). ``value_getter(item) -> str`` is the stable id.
    """
    def _q(guild_id):
        return query(guild_id) if query is not None else {"guild_id": guild_id}

    async def _items(guild_id):
        return await list_documents(collection, _q(guild_id))

    async def _count(guild_id):
        return await count_documents(collection, _q(guild_id))

    async def _action(guild_id, value):
        if delete_query is not None:
            q = delete_query(guild_id, value)
        else:
            q = dict(_q(guild_id)); q[id_field] = value
        return await delete_document(collection, q)

    return PanelNode(
        key=key, label=label, kind="paginated_list", description=description,
        list_get_items=_items, list_count=_count, list_format_line=line_formatter,
        list_item_value=value_getter, list_item_option_label=option_label,
        list_action_label=action_label, list_action=_action,
        list_action_confirm_line=confirm_line, list_page_size=page_size,
        mod_allowed=mod_allowed, premium_label=premium_label,
    )
