# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""storage_engine.logging — the shared structured logger.

The single, vendored home for the ecosystem's structured logger (colored console + indented/JSON
rotating files, a shared global level via ``LOG_LEVEL``, and a small performance-timing toolkit).
Promoted from the per-bot ``utils/logger.py`` copies so every bot — and the engine itself — logs
through identical code instead of each bot maintaining its own copy.

The engine consumes ``get_logger`` via the sibling ``logging_compat`` seam; bots import the public
surface straight from here::

    from storage.logging import get_logger, setup_application_logging

Naming note: this package is called ``logging``, but ``import logging`` inside these modules is an
absolute import and always resolves to the stdlib — only ``from .logging import ...`` (leading
dot) reaches this package.
"""

from __future__ import annotations

from .factory import LoggerManager, get_logger, set_global_level
from .formatters import (
    ColoredConsoleFormatter,
    IndentedFormatter,
    JSONFormatter,
    LogFilter,
)
from .performance import PerformanceLogger, log_context, log_performance
from .setup import (
    get_debug_logger,
    get_production_logger,
    get_simple_logger,
    setup_application_logging,
)

__all__ = [
    "get_logger",
    "setup_application_logging",
    "set_global_level",
    "log_performance",
    "log_context",
    "PerformanceLogger",
    "get_simple_logger",
    "get_debug_logger",
    "get_production_logger",
    "LoggerManager",
    "ColoredConsoleFormatter",
    "IndentedFormatter",
    "JSONFormatter",
    "LogFilter",
]
