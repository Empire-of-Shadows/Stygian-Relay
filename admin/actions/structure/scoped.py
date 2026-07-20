# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Scoped reset/delete action factories (data wipe + bot-specific sub-actions).

These generalize the bots' bespoke reset/delete handlers. The reusable part — wiping a
list of collections scoped by ids — is done by ``mutate_scoped``. The bot-specific part is
supplied as **sub-actions**: async ``before`` / ``after`` hooks the bot passes in. Keep a
note of known sub-actions right above the action that uses them, e.g.:

    # Sub-actions (bot-supplied hooks):
    #   ecom "Reset User Stats":  after = strip level/active/prestige roles
    #                             (role_manager.remove_all_bot_roles, color+achievement kept)
    #   ecom "Delete User Data":  after = strip ALL bot roles (color + achievement included)
    #                             typed_confirm = the member's username
    #   ecom "Delete Guild Data": typed_confirm = str(guild.id)

``before``/``after`` run inside the same deferred interaction; if ``after`` returns a dict it
is merged into the result passed to ``success_text``. ``typed_confirm`` gates the action
behind a typed-match modal (generalizes Ecom's verify_*_deletion_confirmation).
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Union

import discord

from ...views.panel_engine import PanelNode, ActionContext, PanelInputModal, build_confirm_view
from ...views.base import (
    AdminLayoutBuilder, readonly_container, editable_container, notice_container,
    build_notice_layout, cid,
)
from ..collections.scoped import mutate_scoped


async def _back_to_parent(cog, ci, guild, ctx: ActionContext, *, fallback="Closed."):
    if ctx.parent_node is not None:
        await cog._navigate_to(
            ci, ctx.parent_node, guild, parent_node=ctx.grandparent_node,
            edit=True, refresh_parent=ctx.refresh_parent, session=ctx.session,
        )
    else:
        await ci.response.edit_message(view=AdminLayoutBuilder().add_text(fallback).build())


def _make_runner(cog, guild, ctx, *, key, label, specs, scope, require, stringify_ids,
                 before, after, success_text, member=None):
    """Return an async ``run(interaction)`` performing the full scoped pipeline."""
    async def _run(ci: discord.Interaction):
        if not cog._check_cooldown(ci.user.id, key):
            await ci.response.send_message(
                view=build_notice_layout("Slow Down", "Please wait a moment before trying again."),
                ephemeral=True,
            )
            return
        await ci.response.defer(ephemeral=True)
        try:
            if before is not None:
                await (before(guild, member) if member is not None else before(guild))
            result = await mutate_scoped(
                specs, scope, require=require, stringify_ids=stringify_ids,
            )
            if after is not None:
                extra = await (after(guild, member, result) if member is not None else after(guild, result))
                if isinstance(extra, dict):
                    result = {**result, **extra}
        except ValueError:
            await ci.followup.send(
                view=build_notice_layout("Not Configured", f"**{label}** is missing required settings."),
                ephemeral=True,
            )
            return
        except Exception:
            await ci.followup.send(
                view=build_notice_layout("Failed", f"Could not complete **{label}**."),
                ephemeral=True,
            )
            return

        await _back_to_parent(cog, ci, guild, ctx)
        if ctx.refresh_parent:
            await ctx.refresh_parent()
        if success_text is not None:
            msg = success_text(result, member) if member is not None else success_text(result)
        else:
            msg = f"Affected {result.get('documents_affected', 0)} document(s)."
        await ci.followup.send(view=build_notice_layout(label, msg), ephemeral=True)

    return _run


def _typed_modal(label, expected, on_pass):
    """A PanelInputModal that only calls ``on_pass`` when the typed text matches ``expected``."""
    async def _submit(mi: discord.Interaction, raw: str):
        if raw.strip() != str(expected):
            await mi.response.send_message(
                view=build_notice_layout("Does Not Match", "Confirmation text did not match. Cancelled."),
                ephemeral=True,
            )
            return
        await on_pass(mi)

    return PanelInputModal(
        title=f"Confirm {label}"[:45],
        label="Type to confirm",
        placeholder=str(expected),
        min_length=0,
        max_length=200,
        default="",
        on_submit_callback=_submit,
    )


def scoped_guild_action(
    key, *, label, specs: Sequence[dict],
    confirm_text: Optional[str] = None,
    typed_confirm: Optional[Callable] = None,
    before: Optional[Callable] = None,
    after: Optional[Callable] = None,
    stringify_ids: bool = False,
    require=("guild_id",),
    description="", success_text: Optional[Callable] = None,
    mod_allowed=False, premium_label=None,
) -> PanelNode:
    """Guild-scoped reset/delete: optional confirm/typed-confirm, then mutate ``specs`` over
    ``{"guild_id": gid}`` with ``before``/``after`` sub-action hooks.

    See module docstring for the sub-action convention.
    ``typed_confirm(guild) -> str`` enables a typed-match gate; ``success_text(result) -> str``.
    """
    async def _on_run(cog, interaction, guild, ctx: ActionContext):
        scope = {"guild_id": guild.id}
        run = _make_runner(
            cog, guild, ctx, key=key, label=label, specs=specs, scope=scope,
            require=require, stringify_ids=stringify_ids, before=before, after=after,
            success_text=success_text,
        )

        if typed_confirm is not None:
            expected = typed_confirm(guild)
            builder = AdminLayoutBuilder()
            builder.add_header(f"## {label}?")
            builder.add_item(notice_container(discord.ui.TextDisplay(
                (confirm_text or f"This will run **{label}**.")
                + f"\n\nType `{expected}` to confirm."
            )))
            btn = discord.ui.Button(label="Confirm…", style=discord.ButtonStyle.danger,
                                    custom_id=cid("scoped", "typed", key))

            async def _open(bi):
                await bi.response.send_modal(_typed_modal(label, expected, run))

            btn.callback = _open
            row = discord.ui.ActionRow(); row.add_item(btn)
            builder.add_item(editable_container(row))

            async def _back(ci):
                await _back_to_parent(cog, ci, guild, ctx)
            back_btn = discord.ui.Button(label=ctx.back_label or "Back",
                                         style=discord.ButtonStyle.secondary,
                                         custom_id=cid("scoped", "back", key))
            back_btn.callback = _back
            brow = discord.ui.ActionRow(); brow.add_item(back_btn)
            builder.add_item(brow)
            await cog._send_or_edit(interaction, builder.build(), ctx.edit)
        else:
            async def _cancel(ci):
                await _back_to_parent(cog, ci, guild, ctx, fallback="Cancelled.")
            layout = build_confirm_view(
                f"{label}?", confirm_text or f"Run **{label}**?", run, _cancel,
                confirm_label=label, key=key,
            )
            await cog._send_or_edit(interaction, layout, ctx.edit)

    return PanelNode(
        key=key, label=label, kind="action", description=description,
        on_run=_on_run, mod_allowed=mod_allowed, premium_label=premium_label,
    )


def scoped_member_action(
    key, *, label, specs: Sequence[dict],
    confirm_text: Optional[Union[str, Callable]] = None,
    typed_confirm: Optional[Callable] = None,
    before: Optional[Callable] = None,
    after: Optional[Callable] = None,
    stringify_ids: bool = False,
    require=("guild_id", "user_id"),
    description="", placeholder="Select a member...",
    success_text: Optional[Callable] = None,
    mod_allowed=False, premium_label=None,
) -> PanelNode:
    """Member-scoped reset/delete: pick a member, optional confirm/typed-confirm, then mutate
    ``specs`` over ``{"guild_id", "user_id"}`` with ``before``/``after`` sub-action hooks.

    ``confirm_text`` may be ``str`` or ``(member) -> str``; ``typed_confirm(guild, member) ->
    str`` enables a typed-match gate; ``success_text(result, member) -> str``.
    """
    async def _on_run(cog, interaction, guild, ctx: ActionContext):
        builder = AdminLayoutBuilder()
        builder.add_header(f"## {label}")
        builder.add_item(readonly_container(
            discord.ui.TextDisplay(description or f"Select a member for **{label}**.")
        ))

        select = discord.ui.UserSelect(
            placeholder=placeholder, min_values=1, max_values=1,
            custom_id=cid("scoped", "member", key),
        )

        async def _picked(si: discord.Interaction):
            member = select.values[0]
            scope = {"guild_id": guild.id, "user_id": member.id}
            run = _make_runner(
                cog, guild, ctx, key=key, label=label, specs=specs, scope=scope,
                require=require, stringify_ids=stringify_ids, before=before, after=after,
                success_text=success_text, member=member,
            )
            if typed_confirm is not None:
                expected = typed_confirm(guild, member)
                await si.response.send_modal(_typed_modal(label, expected, run))
            elif confirm_text is not None:
                ctext = confirm_text(member) if callable(confirm_text) else confirm_text

                async def _cancel(ci):
                    await _back_to_parent(cog, ci, guild, ctx, fallback="Cancelled.")
                layout = build_confirm_view(
                    f"{label}?", ctext, run, _cancel, confirm_label=label, key=key,
                )
                await si.response.edit_message(view=layout)
            else:
                await run(si)

        select.callback = _picked
        srow = discord.ui.ActionRow(); srow.add_item(select)
        builder.add_item(editable_container(srow))

        async def _back(ci):
            await _back_to_parent(cog, ci, guild, ctx)
        back_btn = discord.ui.Button(label=ctx.back_label or "Back",
                                     style=discord.ButtonStyle.secondary,
                                     custom_id=cid("scoped", "back", key))
        back_btn.callback = _back
        brow = discord.ui.ActionRow(); brow.add_item(back_btn)
        builder.add_item(brow)

        await cog._send_or_edit(interaction, builder.build(), ctx.edit)

    return PanelNode(
        key=key, label=label, kind="action", description=description,
        on_run=_on_run, mod_allowed=mod_allowed, premium_label=premium_label,
    )
