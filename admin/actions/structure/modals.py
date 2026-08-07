# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Modal-driven action factory: open a single-field modal and run a custom submit handler.

Generalizes flows whose submit has a *side effect* rather than storing to config and so
don't fit the ``(guild_id, values)`` leaf contract - e.g. premium-code redemption
(Reminder/Decree) or create-entity-from-a-name (see ``create_role_action`` /
``create_channel_action`` in ``actions/discord_objects``).
"""

from __future__ import annotations

from typing import Callable, Optional

import discord

from ...views.panel_engine import PanelNode, ActionContext, PanelInputModal
from ...views.base import (
    AdminLayoutBuilder, readonly_container, editable_container, notice_container,
    build_notice_layout, cid,
)


def modal_action(
    key, *, label, on_submit: Callable,
    description="", status: Optional[Callable] = None,
    button_label=None, modal_title=None, field_label="Value",
    placeholder="", min_length=0, max_length=200, paragraph=False,
    success_text: Optional[Callable] = None,
    permission_check: Optional[Callable] = None,
    validator: Optional[Callable] = None,
    premium_label=None,
) -> PanelNode:
    """An ``action`` node: shows an optional status line + a button that opens a one-field
    modal, then runs ``on_submit(guild, value) -> result``.

    ``status(guild_id) -> str`` (async, optional) renders a current-status line.
    ``success_text(result) -> str`` formats the success notice (default "Done.").
    ``permission_check(guild) -> (ok, error)`` (sync, optional) runs at the open
    button click, BEFORE the modal: a missing bot permission is refused with a
    notice instead of failing after the admin has typed a value (standard §11).
    ``validator(raw) -> (ok, value, error)`` (sync, optional) runs on submit before
    ``on_submit``; the validated ``value`` is what ``on_submit`` receives.

    Every failure notice after the modal (cooldown, validation, on_submit error)
    carries a Try Again button that reopens the modal with the rejected input
    pre-filled - Discord forbids answering a modal submit with another modal, so
    the button hop is the closest the API allows to "reopen the modal".
    """
    async def _on_run(cog, interaction, guild, ctx: ActionContext):
        builder = AdminLayoutBuilder()
        builder.add_header(f"## {label}")
        if description:
            builder.add_item(readonly_container(discord.ui.TextDisplay(description)))
        if status is not None:
            try:
                status_text = await status(guild.id)
            except Exception:
                status_text = ""
            if status_text:
                builder.add_item(readonly_container(discord.ui.TextDisplay(status_text)))

        def _retry_layout(body: str, previous: str) -> discord.ui.LayoutView:
            """Failure notice + Try Again reopening the modal with the input kept."""
            retry_btn = discord.ui.Button(
                label="Try Again", style=discord.ButtonStyle.primary,
                custom_id=cid("modal_action", "retry", key),
            )

            async def _retry(ri: discord.Interaction):
                await _send_modal(ri, default=previous)

            retry_btn.callback = _retry
            retry_row = discord.ui.ActionRow()
            retry_row.add_item(retry_btn)
            layout = discord.ui.LayoutView()
            layout.add_item(notice_container(
                discord.ui.TextDisplay(f"## {label}\n{body}"), retry_row,
            ))
            return layout

        async def _handle_submit(mi: discord.Interaction, raw: str):
            if not cog._check_cooldown(mi.user.id, key, guild.id):
                await mi.response.send_message(
                    view=_retry_layout("Please wait a moment before trying again.", raw),
                    ephemeral=True,
                )
                return
            value = raw
            if validator is not None:
                ok, value, error = validator(raw)
                if not ok:
                    await mi.response.send_message(
                        view=_retry_layout(error or "That value is not valid.", raw),
                        ephemeral=True,
                    )
                    return
            await mi.response.defer(ephemeral=True)
            try:
                result = await on_submit(guild, value)
            except Exception:
                await mi.followup.send(
                    view=_retry_layout(f"Could not complete **{label}**.", raw),
                    ephemeral=True,
                )
                return
            if ctx.refresh_parent:
                await ctx.refresh_parent()
            msg = success_text(result) if success_text else "Done."
            await mi.followup.send(view=build_notice_layout(label, msg), ephemeral=True)

        async def _send_modal(bi: discord.Interaction, default: str = ""):
            modal = PanelInputModal(
                title=modal_title or label,
                label=field_label,
                placeholder=placeholder,
                min_length=min_length,
                max_length=max_length,
                default=default,
                on_submit_callback=_handle_submit,
                paragraph=paragraph,
                required=True,
            )
            await bi.response.send_modal(modal)

        btn = discord.ui.Button(
            label=button_label or f"Set {label}",
            style=discord.ButtonStyle.primary,
            custom_id=cid("modal_action", "open", key),
        )

        async def _open(bi: discord.Interaction):
            if permission_check is not None:
                ok, error = permission_check(guild)
                if not ok:
                    await bi.response.send_message(
                        view=build_notice_layout("Missing Permission", error or ""),
                        ephemeral=True,
                    )
                    return
            await _send_modal(bi)

        btn.callback = _open
        open_row = discord.ui.ActionRow()
        open_row.add_item(btn)
        builder.add_item(editable_container(open_row))

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
            custom_id=cid("modal_action", "back", key),
        )
        back_btn.callback = _back
        back_row = discord.ui.ActionRow()
        back_row.add_item(back_btn)
        builder.add_item(back_row)

        await cog._send_or_edit(interaction, builder.build(), ctx.edit)

    return PanelNode(
        key=key, label=label, kind="action", description=description,
        on_run=_on_run, premium_label=premium_label,
    )
