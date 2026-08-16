# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""Reads the bot-owned bindings seam and fills in every optional default.

The engine imports ONE thing from a bot: ``ipc/settings/bindings.py``. Keeping
that read in a single module means the seam contract is stated once, the
defaults live next to it, and neither the server nor the client grows its own
opinion about what a missing setting means.

The seam contract (see the bindings reference in ``EmpireSystems/Settings/``):

    SERVICE_NAME    str                  required - this bot's name on the wire
    BIND_PORT       int                  required to SERVE - the 510NN IPC port
    SHARED_SECRET   str                  required - identical across the fleet
    PEERS           dict[str, str]       service name -> base URL
    BIND_HOST       str                  default "0.0.0.0" (container-internal)
    DEFAULT_TIMEOUT float                default 5.0 seconds
    ALLOWED_CALLERS set[str] | None      default None = any caller with the key
    build_idempotency_store(db_manager)  optional - durable exactly-once store
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Optional, Set

from storage.log import get_logger

logger = get_logger("IPC")

_SEAM_MODULE = "ipc.settings.bindings"

_DEFAULTS: Dict[str, Any] = {
    "SERVICE_NAME": "",
    "BIND_HOST": "0.0.0.0",
    "BIND_PORT": 0,
    "SHARED_SECRET": "",
    "PEERS": {},
    "DEFAULT_TIMEOUT": 5.0,
    "ALLOWED_CALLERS": None,
}

_bindings: Any = None
_load_failed = False


def _seam() -> Any:
    """Import the bindings seam once. A missing seam disables IPC entirely."""
    global _bindings, _load_failed
    if _bindings is not None or _load_failed:
        return _bindings
    try:
        _bindings = importlib.import_module(_SEAM_MODULE)
    except ModuleNotFoundError:
        logger.debug(f"No {_SEAM_MODULE} - IPC is not configured for this bot")
        _load_failed = True
    except Exception:
        logger.exception(f"{_SEAM_MODULE} failed to import - IPC is disabled")
        _load_failed = True
    return _bindings


def setting(name: str) -> Any:
    """One seam setting, or its default."""
    seam = _seam()
    if seam is None:
        return _DEFAULTS.get(name)
    return getattr(seam, name, _DEFAULTS.get(name))


def service_name() -> str:
    return str(setting("SERVICE_NAME") or "")


def shared_secret() -> str:
    return str(setting("SHARED_SECRET") or "")


def bind_host() -> str:
    return str(setting("BIND_HOST") or "0.0.0.0")


def bind_port() -> int:
    try:
        return int(setting("BIND_PORT") or 0)
    except (TypeError, ValueError):
        return 0


def default_timeout() -> float:
    try:
        return float(setting("DEFAULT_TIMEOUT") or 5.0)
    except (TypeError, ValueError):
        return 5.0


def allowed_callers() -> Optional[Set[str]]:
    raw = setting("ALLOWED_CALLERS")
    if raw is None:
        return None
    return {str(x) for x in raw}


def peer_url(service: str) -> Optional[str]:
    peers = setting("PEERS") or {}
    url = peers.get(str(service))
    return str(url).rstrip("/") if url else None


def build_idempotency_store(db_manager: Any) -> Any:
    """The seam's durable store, if it provides one."""
    seam = _seam()
    builder = getattr(seam, "build_idempotency_store", None) if seam else None
    if builder is None:
        return None
    try:
        return builder(db_manager)
    except Exception:
        logger.exception("build_idempotency_store() failed - falling back to in-memory")
        return None


def reset_cache() -> None:
    """Drop the cached seam import. Tests only."""
    global _bindings, _load_failed
    _bindings = None
    _load_failed = False
