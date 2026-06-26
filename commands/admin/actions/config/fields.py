# ───────────────────────────────────────────────────────────────────────────
# VENDORED from admin_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Config-field doers — read/write per-guild config through the bindings seam.

Generic over which field (a dotted ``path``) and which backend (each bot's
``bindings`` adapts ``config_get``/``config_set``/``config_unset`` to its own
config manager). These back the leaf factories in ``..config.leaves``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ...bindings import config_get, config_set, config_unset, invalidate_caches

logger = logging.getLogger("AdminActions.config")


def safe_invalidate(guild_id: int) -> None:
    """Invalidate per-guild caches, swallowing backend errors."""
    try:
        invalidate_caches(guild_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("invalidate_caches failed for %s: %s", guild_id, exc)


async def get_config_field(guild_id: int, path: str, default: Any = None) -> Any:
    """Read a per-guild config value at a dotted ``path``."""
    return await config_get(guild_id, path, default)


async def set_config_field(guild_id: int, path: str, value: Any) -> bool:
    """Write ``value`` to a per-guild config dotted ``path`` (+ invalidate caches)."""
    ok = await config_set(guild_id, path, value)
    if ok:
        safe_invalidate(guild_id)
    return ok


async def clear_config_field(guild_id: int, path: str) -> bool:
    """Remove / reset a per-guild config dotted ``path`` (+ invalidate caches)."""
    ok = await config_unset(guild_id, path)
    if ok:
        safe_invalidate(guild_id)
    return ok


async def toggle_config_field(guild_id: int, path: str, enabled: Optional[bool] = None) -> bool:
    """Flip (or set) a boolean config field. Returns the NEW value."""
    new_value = (not bool(await config_get(guild_id, path, False))) if enabled is None else bool(enabled)
    await config_set(guild_id, path, new_value)
    safe_invalidate(guild_id)
    return new_value


async def get_config_list(guild_id: int, path: str) -> list:
    """Read a per-guild config list (empty list when unset)."""
    value = await config_get(guild_id, path, [])
    return list(value) if value else []


async def set_config_list(guild_id: int, path: str, values: list) -> bool:
    """Write a per-guild config list (+ invalidate caches)."""
    ok = await config_set(guild_id, path, list(values))
    if ok:
        safe_invalidate(guild_id)
    return ok


def bool_toggle(path: str):
    """Return ``(toggle_get, toggle_set)`` callables backed by a config bool at ``path``.

    Pass to ``menu_group(toggle_path=…)`` (which calls this) or use directly for a
    feature on/off toggle on a menu node.
    """
    async def _get(guild_id: int) -> bool:
        return bool(await get_config_field(guild_id, path, False))

    async def _set(guild_id: int, enabled: bool) -> bool:
        await set_config_field(guild_id, path, bool(enabled))
        return True

    return _get, _set
