# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""storage_engine.log — the shared, loguru-powered structured logger.

The single vendored home for the ecosystem's logger. **loguru** does the rendering (colored,
aligned console + rotating file + optional JSON, beautiful tracebacks, built-in rotation and
retention); the stdlib is kept as the front door so ``get_logger`` returns a real
``logging.Logger`` and every call site — plus discord.py / pymongo — funnels into loguru via an
``InterceptHandler``.

Bots import the public surface::

    from storage.log import get_logger, setup_application_logging

The engine consumes ``get_logger`` via the sibling ``logging_compat`` seam.

Naming note: this package is ``log`` (not ``logging``) so ``import logging`` is always the stdlib
and can never be shadowed by this directory.
"""

from __future__ import annotations

# Re-exported for opt-in richness (logger.bind / logger.catch / structured kwargs).
from loguru import logger

from .factory import (
    CONSOLE_FORMAT,
    FILE_FORMAT,
    InterceptHandler,
    get_logger,
    set_global_level,
)
from .performance import PerformanceLogger, log_context, log_performance
from .setup import (
    get_debug_logger,
    get_production_logger,
    get_simple_logger,
    setup_application_logging,
)

__all__ = [
    "logger",
    "get_logger",
    "setup_application_logging",
    "set_global_level",
    "log_performance",
    "log_context",
    "PerformanceLogger",
    "get_simple_logger",
    "get_debug_logger",
    "get_production_logger",
    "InterceptHandler",
    "CONSOLE_FORMAT",
    "FILE_FORMAT",
]
