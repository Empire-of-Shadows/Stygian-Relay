# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Confirm-gated action factories: a generic confirm flow + a collection purge."""

from __future__ import annotations

from typing import Optional, Callable

from ...views.panel_engine import PanelNode, ActionContext, build_confirm_view
from ...views.base import build_notice_layout, create_empty_layout
from ..collections.documents import purge_collection
from ..config.fields import safe_invalidate


def confirm_action(
    key, *, label, confirm_text, run, description="", confirm_label=None,
    success_text: Optional[Callable] = None, mod_allowed=False, premium_label=None,
) -> PanelNode:
    """An ``action`` node that shows a Confirm/Cancel prompt, then runs ``run(guild_id)``.

    ``run(guild_id) -> Any`` performs the operation; ``success_text(result) -> str``
    formats the result notice (default "Done.").
    """
    async def _on_run(cog, interaction, guild, ctx: ActionContext):
        async def _back(ci):
            if ctx.parent_node is not None:
                await cog._navigate_to(
                    ci, ctx.parent_node, guild, parent_node=ctx.grandparent_node,
                    edit=True, refresh_parent=ctx.refresh_parent, session=ctx.session,
                )
            else:
                await ci.response.edit_message(view=create_empty_layout("Cancelled."))

        async def _confirm(ci):
            if not cog._check_cooldown(ci.user.id, key, guild.id):
                await ci.response.send_message(
                    view=build_notice_layout("Slow Down", "Please wait a moment before trying again."),
                    ephemeral=True,
                )
                return
            await ci.response.defer(ephemeral=True)
            try:
                result = await run(guild.id)
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
            msg = success_text(result) if success_text else "Done."
            await ci.followup.send(view=build_notice_layout(label, msg), ephemeral=True)

        layout = build_confirm_view(
            f"{label}?", confirm_text, _confirm, _back,
            confirm_label=confirm_label or label, key=key,
        )
        await cog._send_or_edit(interaction, layout, ctx.edit)

    return PanelNode(
        key=key, label=label, kind="action", description=description,
        on_run=_on_run, mod_allowed=mod_allowed, premium_label=premium_label,
    )


def purge_action(key, *, collection, label, confirm_text, query: Optional[Callable] = None,
                 description="", mod_allowed=False, premium_label=None) -> PanelNode:
    """A confirm-gated ``action`` that purges all documents in ``collection`` matching
    ``query(guild_id)`` (default ``{"guild_id": str(guild_id)}`` - IDs are stored as
    strings, the ecosystem standard; a collection that deviates must pass its own
    ``query``)."""
    async def _run(guild_id):
        if query is not None:
            q = query(guild_id)
        else:
            q = {"guild_id": str(guild_id)}
        removed = await purge_collection(collection, q)
        safe_invalidate(guild_id)
        return removed

    return confirm_action(
        key, label=label, confirm_text=confirm_text, run=_run, description=description,
        success_text=lambda n: f"Removed {n} item(s).",
        mod_allowed=mod_allowed, premium_label=premium_label,
    )
