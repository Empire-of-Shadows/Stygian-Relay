# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Application-level logging setup and convenience factories.

``setup_application_logging`` is the one call a bot makes at startup: it fixes the shared global
level (``LOG_LEVEL`` env wins) and builds the main app logger (+ an optional JSON performance
logger). The ``get_simple/debug/production_logger`` helpers are thin presets over ``get_logger``.
"""

from __future__ import annotations

import logging
import os

from .factory import _resolve_log_level, get_logger, set_global_level


def setup_application_logging(
        app_name: str,
        log_level: int = logging.INFO,
        log_dir: str = "logs",
        enable_performance_logging: bool = True,
        max_file_size: int = 10 * 1024 * 1024,  # 10 MB
        backup_count: int = 5
) -> logging.Logger:
    """Set up application-wide logging configuration.

    :param app_name: Name of the application.
    :param log_level: Global logging level (the ``LOG_LEVEL`` env var still wins).
    :param log_dir: Directory for log files.
    :param enable_performance_logging: Whether to create a JSON performance logger.
    :param max_file_size: Maximum size per log file.
    :param backup_count: Number of backup files to keep.
    :return: Main application logger.
    """
    # Establish the single shared level for every logger built via get_logger.
    # An explicit LOG_LEVEL env var still wins over the passed-in default.
    resolved_level = set_global_level(
        _resolve_log_level(os.getenv("LOG_LEVEL"), _resolve_log_level(log_level))
    )

    # Create main application logger
    main_logger = get_logger(
        module_name=app_name,
        level=resolved_level,
        log_dir=log_dir,
        max_file_size=max_file_size,
        backup_count=backup_count,
        colored_console=True,
        json_format=False
    )

    # Add performance logging if enabled
    if enable_performance_logging:
        get_logger(
            module_name=f"{app_name}.performance",
            level=logging.DEBUG,
            log_dir=log_dir,
            console_output=False,  # Performance logs go to file only
            json_format=True  # JSON format for easier parsing
        )

    main_logger.info(f"Application logging initialized for: {app_name}")

    return main_logger


# Convenience presets over get_logger.
def get_simple_logger(name: str) -> logging.Logger:
    """Get a simple logger with basic configuration."""
    return get_logger(name, level=logging.INFO)


def get_debug_logger(name: str) -> logging.Logger:
    """Get a debug logger with verbose output."""
    return get_logger(name, level=logging.DEBUG, colored_console=True)


def get_production_logger(name: str) -> logging.Logger:
    """Get a production logger with JSON format and no console output."""
    return get_logger(
        name,
        level=logging.WARNING,
        console_output=False,
        json_format=True,
        max_file_size=50 * 1024 * 1024,  # 50 MB
        backup_count=10
    )
