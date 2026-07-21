# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Feature builder: an allow / block channel-list pair with mutual exclusion.

Generalizes The Decree's quote channel allow/block lists: two multi channel
selects where adding a channel to one list removes it from the other. A bot calls
``access_list_pair(...)`` with two config paths and drops the returned nodes into a
menu.
"""

from __future__ import annotations

from typing import Optional

from ...views.panel_engine import PanelNode
from ..config.fields import get_config_list, set_config_list


def _exclusive_leaf(key, path, other_path, *, label, description, channel_types,
                    max_values, mod_allowed, premium_label) -> PanelNode:
    async def _get(guild_id):
        return [int(x) for x in await get_config_list(guild_id, path)]

    async def _set(guild_id, values):
        ids = [int(v) for v in values]
        ok = await set_config_list(guild_id, path, ids)
        # Mutual exclusion: drop any of these ids from the sibling list.
        other = [int(x) for x in await get_config_list(guild_id, other_path)]
        pruned = [x for x in other if x not in ids]
        if pruned != other:
            await set_config_list(guild_id, other_path, pruned)
        return ok

    async def _clear(guild_id):
        return await set_config_list(guild_id, path, [])

    return PanelNode(
        key=key, label=label, kind="channel_select", description=description,
        channel_types=channel_types, get_values=_get, set_values=_set, clear_values=_clear,
        min_values=0, max_values=max_values, mod_allowed=mod_allowed, premium_label=premium_label,
    )


def access_list_pair(
    *, allow_key="allow", block_key="block", allow_path, block_path,
    allow_label="Allowed Channels", block_label="Blocked Channels",
    allow_description="", block_description="", channel_types=None, max_values=25,
    mod_allowed=False, premium_label=None,
) -> dict[str, PanelNode]:
    """Return ``{allow_key: node, block_key: node}`` - two mutually-exclusive channel lists."""
    return {
        allow_key: _exclusive_leaf(
            allow_key, allow_path, block_path, label=allow_label,
            description=allow_description, channel_types=channel_types,
            max_values=max_values, mod_allowed=mod_allowed, premium_label=premium_label,
        ),
        block_key: _exclusive_leaf(
            block_key, block_path, allow_path, label=block_label,
            description=block_description, channel_types=channel_types,
            max_values=max_values, mod_allowed=mod_allowed, premium_label=premium_label,
        ),
    }
