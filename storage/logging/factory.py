# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""The logger factory — ``get_logger`` plus the manager/hook plumbing behind it.

Owns the single shared log level (``LOG_LEVEL`` env, settable via ``set_global_level``) and the
``LoggerManager`` singleton that caches configured loggers so a name is only wired once.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Any, Callable, Dict, List, Optional

from .formatters import (
    ColoredConsoleFormatter,
    IndentedFormatter,
    JSONFormatter,
    LogFilter,
)


def _resolve_log_level(value: Any, default: int = logging.INFO) -> int:
    """Coerce an int / level-name string (e.g. "DEBUG") into a logging level int.

    Falls back to ``default`` for empty/unknown names so a bad ``LOG_LEVEL`` value can never
    produce a non-int that would break ``logger.setLevel``.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        resolved = logging.getLevelName(value.strip().upper())
        return resolved if isinstance(resolved, int) else default
    return default


# Single global level shared by every logger created via ``get_logger``. Set once by
# ``setup_application_logging`` (via ``set_global_level``) and overridable with the ``LOG_LEVEL``
# env var, so the whole app has one knob instead of per-module DEBUG drift.
_GLOBAL_LOG_LEVEL: int = _resolve_log_level(os.getenv("LOG_LEVEL"), logging.INFO)


def set_global_level(level: Any) -> int:
    """Set the shared level used by every ``get_logger`` call that doesn't pass its own.

    Returns the resolved int level. Called by ``setup_application_logging``.
    """
    global _GLOBAL_LOG_LEVEL
    _GLOBAL_LOG_LEVEL = _resolve_log_level(level)
    return _GLOBAL_LOG_LEVEL


class LoggerManager:
    """Centralized logger management system (process-wide singleton)."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.loggers: Dict[str, logging.Logger] = {}
            self.config: Dict[str, Any] = {}
            self.log_hooks: List[Callable] = []
            self.initialized = True

    def add_hook(self, hook_func: Callable[[logging.LogRecord], None]):
        """Add a hook function that will be called for every log record."""
        self.log_hooks.append(hook_func)

    def remove_hook(self, hook_func: Callable[[logging.LogRecord], None]):
        """Remove a previously added hook function."""
        if hook_func in self.log_hooks:
            self.log_hooks.remove(hook_func)

    def get_all_loggers(self) -> Dict[str, logging.Logger]:
        """Get all managed loggers."""
        return self.loggers.copy()

    def set_global_level(self, level: int):
        """Set logging level for all managed loggers."""
        for logger in self.loggers.values():
            logger.setLevel(level)

    def cleanup_old_logs(self, log_dir: str = "logs", days_to_keep: int = 30):
        """Remove log files older than specified days."""
        if not os.path.exists(log_dir):
            return

        cutoff_time = datetime.now().timestamp() - (days_to_keep * 24 * 60 * 60)

        for filename in os.listdir(log_dir):
            filepath = os.path.join(log_dir, filename)
            if os.path.isfile(filepath) and filename.endswith('.log'):
                if os.path.getmtime(filepath) < cutoff_time:
                    try:
                        os.remove(filepath)
                        print(f"Removed old log file: {filename}")
                    except OSError as e:
                        print(f"Failed to remove {filename}: {e}")


class HookHandler(logging.Handler):
    """Custom handler that triggers registered hooks."""

    def __init__(self, hooks: List[Callable]):
        super().__init__()
        self.hooks = hooks

    def emit(self, record):
        for hook in self.hooks:
            try:
                hook(record)
            except Exception:
                pass  # Don't let hook failures break logging


def get_logger(
        module_name: str,
        log_dir: str = "logs",
        level: Optional[int] = None,
        console_output: bool = True,
        file_output: bool = True,
        json_format: bool = False,
        colored_console: bool = True,
        max_file_size: int = 5 * 1024 * 1024,  # 5 MB
        backup_count: int = 3,
        rotation_type: str = "size",  # "size" or "time"
        time_rotation: str = "midnight",  # for time-based rotation
        custom_format: Optional[str] = None,
        filters: Optional[LogFilter] = None,
        extra_handlers: Optional[List[logging.Handler]] = None
) -> logging.Logger:
    """Enhanced logger factory with multiple configuration options.

    :param module_name: The name of the module using the logger.
    :param log_dir: Directory for log files.
    :param level: Logging level; ``None`` uses the shared global level (see
        ``setup_application_logging`` / ``LOG_LEVEL``).
    :param console_output: Whether to output to console.
    :param file_output: Whether to output to file.
    :param json_format: Whether to use JSON formatting for file output.
    :param colored_console: Whether to use colored console output.
    :param max_file_size: Maximum size per log file (for size-based rotation).
    :param backup_count: Number of backup files to keep.
    :param rotation_type: Type of rotation ("size" or "time").
    :param time_rotation: Time-based rotation interval.
    :param custom_format: Custom log format string.
    :param filters: Custom log filter.
    :param extra_handlers: Additional handlers to add.
    :return: Configured logger instance.
    """
    manager = LoggerManager()

    # Fall back to the single global level unless a caller explicitly overrides it.
    if level is None:
        level = _GLOBAL_LOG_LEVEL

    # Return existing logger if already configured
    if module_name in manager.loggers:
        return manager.loggers[module_name]

    # Ensure the logs directory exists
    if file_output:
        os.makedirs(log_dir, exist_ok=True)

    # Create logger instance
    logger = logging.getLogger(module_name)
    logger.setLevel(level)

    # Clear existing handlers to avoid duplicates
    logger.handlers.clear()

    # Default format
    default_format = custom_format or "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # File handler
    if file_output:
        log_file = os.path.join(log_dir, f"{module_name.replace('.', '_')}.log")

        if rotation_type == "time":
            file_handler = TimedRotatingFileHandler(
                filename=log_file,
                when=time_rotation,
                backupCount=backup_count,
                encoding="utf-8"
            )
        else:  # size-based rotation
            file_handler = RotatingFileHandler(
                filename=log_file,
                maxBytes=max_file_size,
                backupCount=backup_count,
                encoding="utf-8"
            )

        # Choose formatter
        if json_format:
            file_formatter = JSONFormatter()
        else:
            file_formatter = IndentedFormatter(default_format)

        file_handler.setFormatter(file_formatter)

        # Add filter if provided
        if filters:
            file_handler.addFilter(filters.filter)

        logger.addHandler(file_handler)

    # Console handler
    if console_output:
        console_handler = logging.StreamHandler()

        if colored_console:
            console_formatter = ColoredConsoleFormatter(default_format)
        else:
            console_formatter = IndentedFormatter(default_format)

        console_handler.setFormatter(console_formatter)

        # Add filter if provided
        if filters:
            console_handler.addFilter(filters.filter)

        logger.addHandler(console_handler)

    # Add hook handler for registered hooks
    if manager.log_hooks:
        hook_handler = HookHandler(manager.log_hooks)
        logger.addHandler(hook_handler)

    # Add extra handlers
    if extra_handlers:
        for handler in extra_handlers:
            logger.addHandler(handler)

    # Store in manager
    manager.loggers[module_name] = logger

    return logger
