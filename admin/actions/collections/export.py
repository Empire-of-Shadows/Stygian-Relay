# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Export a collection as a file: the doer + an ``export_action`` node factory."""

from __future__ import annotations

import io
import json
from typing import Optional, Callable

import discord

from ...views.panel_engine import PanelNode, ActionContext
from ...views.base import build_notice_layout
from .documents import list_documents


async def export_documents(
    collection: str, query: dict, *, fmt: str = "json", filename: str = "export",
    fields: Optional[list[str]] = None,
) -> discord.File:
    """Export matching documents as a ``discord.File`` in json or csv."""
    docs = await list_documents(collection, query)
    if fmt == "csv":
        import csv
        cols = fields or sorted({k for d in docs for k in d.keys() if k != "_id"})
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for d in docs:
            writer.writerow({c: d.get(c, "") for c in cols})
        return discord.File(io.BytesIO(buf.getvalue().encode("utf-8")), filename=f"{filename}.csv")
    payload = json.dumps(docs, default=str, indent=2).encode("utf-8")
    return discord.File(io.BytesIO(payload), filename=f"{filename}.json")


def export_action(key, *, collection, label, fmt="json", filename="export",
                  query: Optional[Callable] = None, fields=None, description="",
                  mod_allowed=False, premium_label=None, stringify_ids=False) -> PanelNode:
    """An ``action`` node that exports ``collection`` (matching ``query``) ephemerally.

    ``stringify_ids=True`` casts ``guild_id`` to ``str`` in the default query (else it
    exports nothing against string-id collections)."""
    async def _on_run(cog, interaction, guild, ctx: ActionContext):
        if query is not None:
            q = query(guild.id)
        else:
            q = {"guild_id": str(guild.id) if stringify_ids else guild.id}
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        try:
            file = await export_documents(collection, q, fmt=fmt, filename=filename, fields=fields)
            await interaction.followup.send(file=file, ephemeral=True)
        except Exception:
            await interaction.followup.send(
                view=build_notice_layout("Export failed", f"Could not export **{label}**."),
                ephemeral=True,
            )

    return PanelNode(
        key=key, label=label, kind="action", description=description,
        on_run=_on_run, mod_allowed=mod_allowed, premium_label=premium_label,
    )
