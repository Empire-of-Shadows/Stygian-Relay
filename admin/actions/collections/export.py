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


def _json_default(value):
    from datetime import datetime
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def export_documents(
    collection: str, query: dict, *, fmt: str = "json", filename: str = "export",
    fields: Optional[list[str]] = None, limit: Optional[int] = None,
) -> discord.File:
    """Export matching documents as a ``discord.File`` in json or csv.

    ``fields`` limits both formats to those keys; ``_id`` is always excluded.
    Datetimes serialize as ISO-8601 in json."""
    docs = await list_documents(collection, query, limit=limit)
    if fmt == "csv":
        import csv
        cols = fields or sorted({k for d in docs for k in d.keys() if k != "_id"})
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for d in docs:
            writer.writerow({c: d.get(c, "") for c in cols})
        return discord.File(io.BytesIO(buf.getvalue().encode("utf-8")), filename=f"{filename}.csv")
    if fields:
        rows = [{k: d.get(k) for k in fields} for d in docs]
    else:
        rows = [{k: v for k, v in d.items() if k != "_id"} for d in docs]
    payload = json.dumps(rows, default=_json_default, indent=2).encode("utf-8")
    return discord.File(io.BytesIO(payload), filename=f"{filename}.json")


def export_action(key, *, collection, label, fmt="json", filename="export",
                  query: Optional[Callable] = None, fields=None, description="",
                  mod_allowed=False, premium_label=None) -> PanelNode:
    """An ``action`` node that exports ``collection`` (matching ``query``) ephemerally.

    The default query is ``{"guild_id": str(guild.id)}`` - IDs are stored as strings,
    the ecosystem standard; a collection that deviates must pass its own ``query``."""
    async def _on_run(cog, interaction, guild, ctx: ActionContext):
        if query is not None:
            q = query(guild.id)
        else:
            q = {"guild_id": str(guild.id)}
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
