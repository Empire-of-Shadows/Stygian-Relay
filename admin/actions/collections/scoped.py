# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Generic scoped data-mutation doer.

One reusable operation behind the bots' bespoke reset/delete handlers: mutate a *list of
collections* scoped by ids (guild and optionally user). Each spec says how to mutate one
collection — delete the matching docs, or field-reset them (``$unset`` / ``$set``). The
data layer is reached through the bindings seam, so this stays bot-agnostic; the bot only
declares which collections + which mode (and supplies any side effects as sub-action hooks
on the factories in ``actions/structure/scoped.py``).

Safety: refuses to run without at least a ``guild_id`` in scope and one collection spec —
so a misconfigured panel can never wipe a whole collection unscoped.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .documents import purge_collection, upsert_document


def _build_query(scope: dict, *, stringify_ids: bool) -> dict:
    """Build a Mongo query from the non-None entries of ``scope``."""
    query = {}
    for key, value in scope.items():
        if value is None:
            continue
        query[key] = str(value) if stringify_ids else value
    return query


async def mutate_scoped(
    specs: Sequence[dict],
    scope: dict,
    *,
    require: Iterable[str] = ("guild_id",),
    stringify_ids: bool = False,
) -> dict:
    """Delete or field-reset documents across ``specs`` collections, scoped by ``scope``.

    ``specs`` — non-empty list; each entry is a dict:
        {"collection": str,
         "mode": "delete" | "unset" | "set",
         "fields": [...],        # for mode="unset": field names to remove
         "defaults": {...}}      # for mode="set": field -> default value
    ``scope`` — e.g. ``{"guild_id": gid, "user_id": uid}``; the query is built from the
        non-None entries. ``stringify_ids=True`` casts id values to ``str`` (some bots store
        guild/user ids as strings).
    ``require`` — keys that MUST be present and non-None in ``scope`` (default: guild_id).

    Returns ``{"affected_collections": [...], "documents_affected": N}``.
    Raises ``ValueError`` if the safety guard fails (missing required scope or empty specs).
    """
    if not specs:
        raise ValueError("mutate_scoped requires at least one collection spec")
    for key in require:
        if scope.get(key) is None:
            raise ValueError(f"mutate_scoped requires scope[{key!r}] to be set")

    query = _build_query(scope, stringify_ids=stringify_ids)
    if not query:
        raise ValueError("mutate_scoped refuses to run with an empty scope query")

    affected: list[str] = []
    total = 0
    for spec in specs:
        collection = spec["collection"]
        mode = spec.get("mode", "delete")

        if mode == "delete":
            removed = await purge_collection(collection, query)
            if removed:
                total += removed
                affected.append(collection)

        elif mode == "unset":
            fields = spec.get("fields") or []
            if not fields:
                continue
            ok = await upsert_document(
                collection, query, {"$unset": {f: "" for f in fields}}, upsert=False,
            )
            if ok:
                total += 1
                affected.append(collection)

        elif mode == "set":
            defaults = spec.get("defaults") or {}
            if not defaults:
                continue
            ok = await upsert_document(collection, query, {"$set": defaults}, upsert=False)
            if ok:
                total += 1
                affected.append(collection)

        else:
            raise ValueError(f"unknown mutate_scoped mode {mode!r} for {collection!r}")

    return {"affected_collections": affected, "documents_affected": total}
