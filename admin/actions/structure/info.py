# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Read-only information display action factory.

Generalizes the bots' read-only "Info" views (Ecom settings/user/guild summaries and
notification stats, Codex view-status) into a reusable ``action`` node: the bot supplies
an async ``render`` that returns the body text, and the engine handles layout + Back.
"""

from __future__ import annotations

from typing import Callable, Optional

import discord

from ...views.panel_engine import PanelNode, ActionContext
from ...views.base import AdminLayoutBuilder, readonly_container, cid


def info_action(
    key, *, label, render: Callable, description="", mod_allowed=True, premium_label=None,
) -> PanelNode:
    """An ``action`` node that renders a read-only display on message 2.

    ``render(cog, guild, ctx) -> str`` (async) returns the markdown body to show; a Back
    button returns to the parent menu. Defaults to ``mod_allowed=True`` since info views
    are read-only and mods are typically allowed to view them.
    """
    async def _on_run(cog, interaction, guild, ctx: ActionContext):
        try:
            body = await render(cog, guild, ctx)
        except Exception:
            body = "Could not load this information."

        builder = AdminLayoutBuilder()
        builder.add_header(f"## {label}")
        if description:
            builder.add_item(readonly_container(discord.ui.TextDisplay(description)))
        builder.add_item(readonly_container(discord.ui.TextDisplay(body or "*No data.*")))

        async def _back(ci):
            if ctx.parent_node is not None:
                await cog._navigate_to(
                    ci, ctx.parent_node, guild, parent_node=ctx.grandparent_node,
                    edit=True, refresh_parent=ctx.refresh_parent, session=ctx.session,
                )
            else:
                await ci.response.edit_message(view=AdminLayoutBuilder().add_text("Closed.").build())

        back_btn = discord.ui.Button(
            label=ctx.back_label or "Back",
            style=discord.ButtonStyle.secondary,
            custom_id=cid("info", "back", key),
        )
        back_btn.callback = _back
        row = discord.ui.ActionRow()
        row.add_item(back_btn)
        builder.add_item(row)

        await cog._send_or_edit(interaction, builder.build(), ctx.edit)

    return PanelNode(
        key=key, label=label, kind="action", description=description,
        on_run=_on_run, mod_allowed=mod_allowed, premium_label=premium_label,
    )
