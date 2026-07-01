# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Internal logger seam for engine modules.

Engine modules import the logger as ``from ..logging_compat import get_logger`` (or ``.`` from the
package root). The logger now ships inside the engine itself — ``storage_engine.logging`` — so this
is a one-line re-export: always present, no bot dependency, no stdlib fallback.

Kept as a stable seam so the engine modules don't all have to import ``.logging`` directly.
"""

from __future__ import annotations

from .logging import get_logger

__all__ = ["get_logger"]
