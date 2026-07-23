# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""Single source of truth for environment loading (+ tiny typed env readers).

Every process/module loads from `docker/.env` (the deploy env), regardless of
the current working directory or which module is imported first. Falls back to
the default `.env` search only if `docker/.env` doesn't exist.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_loaded = False


def load_project_env() -> Path | None:
    """Load docker/.env once (+ a docker/.env.local dev override when present).

    Returns the path loaded, or None for the fallback. ``.env.local`` is loaded
    AFTER the main file with ``override=True`` so local development values win
    over the deploy env (EcomRebuild convention; it is gitignored and absent in
    production, making the override a no-op there).
    """
    global _loaded
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docker" / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            local = parent / "docker" / ".env.local"
            if local.exists():
                load_dotenv(local, override=True)
            _loaded = True
            return candidate
    load_dotenv()
    _loaded = True
    return None


def int_env(name: str, default: int) -> int:
    """Read an integer env var, falling back to ``default`` on unset/invalid values
    (a malformed deploy env must degrade to the default, never crash a caller)."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.getLogger(__name__).warning(
            "Invalid %s=%r; using default %d.", name, raw, default
        )
        return default
