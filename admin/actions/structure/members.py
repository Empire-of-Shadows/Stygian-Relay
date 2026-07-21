# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Member-targeted action factory: pick a user, optionally confirm, then run a handler.

Generalizes Ecom's per-user admin flows (reset user stats/achievements/all, delete user
data) which select a target member via a custom UserSelect view before acting. The bot
supplies ``run(guild_id, user_id)``; the engine handles the picker, optional confirm,
notice, and back-navigation.
"""

from __future__ import annotations

from typing import Callable, Optional, Union

import discord

from ...views.panel_engine import PanelNode, ActionContext, build_confirm_view
from ...views.base import (
    AdminLayoutBuilder, readonly_container, editable_container, build_notice_layout, cid,
)


def member_action(
    key, *, label, run: Callable,
    confirm_text: Optional[Union[str, Callable]] = None,
    description="", placeholder="Select a member...",
    success_text: Optional[Callable] = None, mod_allowed=False, premium_label=None,
) -> PanelNode:
    """An ``action`` node presenting a member picker (UserSelect); on pick it optionally
    shows a Confirm/Cancel prompt, then runs ``run(guild_id, user_id) -> result``.

    ``confirm_text`` : str or ``(member) -> str``; when set, a confirm step is shown.
    ``success_text`` : ``(result, member) -> str``; formats the success notice.
    """
    async def _on_run(cog, interaction, guild, ctx: ActionContext):
        builder = AdminLayoutBuilder()
        builder.add_header(f"## {label}")
        builder.add_item(readonly_container(
            discord.ui.TextDisplay(description or f"Select a member for **{label}**.")
        ))

        select = discord.ui.UserSelect(
            placeholder=placeholder, min_values=1, max_values=1,
            custom_id=cid("member", "select", key),
        )

        async def _run_for(ci: discord.Interaction, member):
            if not cog._check_cooldown(ci.user.id, key, guild.id):
                await ci.response.send_message(
                    view=build_notice_layout("Slow Down", "Please wait a moment before trying again."),
                    ephemeral=True,
                )
                return
            await ci.response.defer(ephemeral=True)
            try:
                result = await run(guild.id, member.id)
            except Exception:
                await ci.followup.send(
                    view=build_notice_layout("Failed", f"Could not complete **{label}**."),
                    ephemeral=True,
                )
                return
            if ctx.parent_node is not None:
                await cog._navigate_to(
                    ci, ctx.parent_node, guild, parent_node=ctx.grandparent_node,
                    edit=True, refresh_parent=ctx.refresh_parent, session=ctx.session,
                )
            if ctx.refresh_parent:
                await ctx.refresh_parent()
            msg = success_text(result, member) if success_text else "Done."
            await ci.followup.send(view=build_notice_layout(label, msg), ephemeral=True)

        async def _picked(si: discord.Interaction):
            member = select.values[0]
            if confirm_text is not None:
                ctext = confirm_text(member) if callable(confirm_text) else confirm_text

                async def _confirm(ci):
                    await _run_for(ci, member)

                async def _cancel(ci):
                    if ctx.parent_node is not None:
                        await cog._navigate_to(
                            ci, ctx.parent_node, guild, parent_node=ctx.grandparent_node,
                            edit=True, refresh_parent=ctx.refresh_parent, session=ctx.session,
                        )
                    else:
                        await ci.response.edit_message(view=AdminLayoutBuilder().add_text("Cancelled.").build())

                layout = build_confirm_view(
                    f"{label}?", ctext, _confirm, _cancel, confirm_label=label, key=key,
                )
                await si.response.edit_message(view=layout)
            else:
                await _run_for(si, member)

        select.callback = _picked
        select_row = discord.ui.ActionRow()
        select_row.add_item(select)
        builder.add_item(editable_container(select_row))

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
            custom_id=cid("member", "back", key),
        )
        back_btn.callback = _back
        back_row = discord.ui.ActionRow()
        back_row.add_item(back_btn)
        builder.add_item(back_row)

        await cog._send_or_edit(interaction, builder.build(), ctx.edit)

    return PanelNode(
        key=key, label=label, kind="action", description=description,
        on_run=_on_run, mod_allowed=mod_allowed, premium_label=premium_label,
    )
