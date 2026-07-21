# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Application-level logging setup and convenience factories.

``setup_application_logging`` is the one call a bot makes at startup: it fixes the shared level
(``LOG_LEVEL`` env wins), installs the loguru sinks (colored console + rotating file + optional
JSON) and the stdlib -> loguru intercept, and silences noisy third-party loggers. The
``get_simple/debug/production_logger`` helpers are thin presets over ``get_logger``.
"""

from __future__ import annotations

import logging
import os

from .factory import (
    _configure_sinks,
    _resolve_log_level,
    _silence_noisy_loggers,
    get_logger,
    set_global_level,
)


def setup_application_logging(
    app_name: str,
    log_level: int = logging.INFO,
    log_dir: str = "logs",
    enable_performance_logging: bool = True,
    max_file_size: int = 10 * 1024 * 1024,  # accepted for compat; loguru rotates at 10 MB
    backup_count: int = 5,  # accepted for compat; loguru retains 10 days
) -> logging.Logger:
    """Set up application-wide logging.

    :param app_name: Application name; used for the log file names and the default logger.
    :param log_level: Base level (the ``LOG_LEVEL`` env var still wins).
    :param log_dir: Directory for ``{app_name}.log`` / ``{app_name}.jsonl``.
    :param enable_performance_logging: When true, also write a structured JSON sink
        (``{app_name}.jsonl``) - this is where performance/structured records land.
    :param max_file_size: Accepted for backwards compat; loguru rotates at 10 MB.
    :param backup_count: Accepted for backwards compat; loguru retains 10 days.
    :return: The main application logger (a stdlib logger routed into loguru).
    """
    resolved_level = set_global_level(
        _resolve_log_level(os.getenv("LOG_LEVEL"), _resolve_log_level(log_level))
    )

    _configure_sinks(
        app_name,
        log_dir=log_dir,
        level=resolved_level,
        console=True,
        file=True,
        json=enable_performance_logging,
    )
    _silence_noisy_loggers()

    main_logger = get_logger(app_name)
    main_logger.info(f"Application logging initialized for: {app_name}")
    return main_logger


# Convenience presets over get_logger. Output config is global (see setup_application_logging);
# these just pin a level on the returned stdlib logger.
def get_simple_logger(name: str) -> logging.Logger:
    """A logger at INFO."""
    return get_logger(name, level=logging.INFO)


def get_debug_logger(name: str) -> logging.Logger:
    """A logger at DEBUG."""
    return get_logger(name, level=logging.DEBUG)


def get_production_logger(name: str) -> logging.Logger:
    """A logger at WARNING."""
    return get_logger(name, level=logging.WARNING)
