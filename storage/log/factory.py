# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Logger factory and the stdlib -> loguru bridge.

``get_logger`` hands back a stdlib :class:`logging.Logger` (call sites rely on the full stdlib
API, e.g. ``logger.isEnabledFor(...)``), while **loguru** is the single sink that actually
renders and writes every record. :class:`InterceptHandler` forwards stdlib records into loguru,
so our own loggers *and* third-party ones (discord.py, pymongo) share one clean, colored,
rotating output. Sinks are configured by ``setup_application_logging`` (see :mod:`.setup`), which
delegates to :func:`_configure_sinks` here.

Naming note: this package is ``log`` (not ``logging``) precisely so ``import logging`` anywhere is
always the stdlib and can never be shadowed by this directory.
"""

from __future__ import annotations

import inspect
import logging
import os
import sys
from typing import Any, List, Optional

from loguru import logger

# loguru's numeric severities line up with the stdlib for the shared levels
# (DEBUG=10, INFO=20, WARNING=30, ERROR=40, CRITICAL=50), so stdlib ints pass straight through.

# Console format uses loguru colour markup; ``extra[name]`` carries the originating logger name
# (bound by InterceptHandler, defaulted via ``logger.configure`` in _configure_sinks).
CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[name]}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)
# File format is the same, sans colour markup.
FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{extra[name]}:{function}:{line} - {message}"
)

# Noisy third-party loggers we pin to WARNING so the console stays readable.
_NOISY_LOGGERS = (
    "discord",
    "discord.gateway",
    "discord.client",
    "discord.http",
    "pymongo",
    "pymongo.connection",
    "pymongo.serverSelection",
    "pymongo.topology",
    "motor",
)


def _resolve_log_level(value: Any, default: int = logging.INFO) -> int:
    """Coerce an int / level-name string (e.g. ``"DEBUG"``) into a logging level int.

    Falls back to ``default`` for empty/unknown names so a bad ``LOG_LEVEL`` can never yield a
    non-int that would break ``setLevel``.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        resolved = logging.getLevelName(value.strip().upper())
        return resolved if isinstance(resolved, int) else default
    return default


# Shared default level (LOG_LEVEL env wins). Consulted by presets and set_global_level.
_GLOBAL_LOG_LEVEL: int = _resolve_log_level(os.getenv("LOG_LEVEL"), logging.INFO)

# Ids of the loguru sinks we added, plus the args used, so set_global_level can reconfigure them.
_SINK_IDS: List[int] = []
_STATE: dict = {}


class InterceptHandler(logging.Handler):
    """Forward stdlib logging records into loguru (the single rendering sink).

    The standard loguru bridge: every record emitted through the stdlib — our ``get_logger``
    loggers as well as third-party libraries — is re-emitted through loguru so it inherits the
    shared format, colours, rotation and retention.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Map the stdlib level to a loguru level name when possible; else fall back to the number.
        try:
            level = logger.level(record.levelname).name
        except (ValueError, KeyError):
            level = record.levelno

        # Walk out of the logging machinery so {function}/{line} point at the real caller.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).bind(name=record.name).log(
            level, record.getMessage()
        )


def _install_intercept(level: int = 0) -> None:
    """Make the stdlib root funnel everything into loguru (root captures at level 0)."""
    logging.basicConfig(handlers=[InterceptHandler()], level=level, force=True)


def _ensure_intercept() -> None:
    """Install the intercept lazily so ``get_logger`` works even before setup is called."""
    root = logging.getLogger()
    if not any(isinstance(h, InterceptHandler) for h in root.handlers):
        _install_intercept()


def _silence_noisy_loggers(level: int = logging.WARNING) -> None:
    """Pin chatty third-party loggers to WARNING for a readable console."""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)


def _configure_sinks(
    app_name: str,
    log_dir: str = "logs",
    level: int = logging.INFO,
    *,
    console: bool = True,
    file: bool = True,
    json: bool = True,
    backtrace: bool = True,
    diagnose: bool = False,
) -> int:
    """Reset loguru and install our console / file / JSON sinks, then wire the stdlib intercept.

    Replaces the old per-logger handlers, ``RotatingFileHandler`` and ``cleanup_old_logs``:
    loguru owns rotation (``10 MB``) and retention (``10 days``). Returns the resolved level.
    """
    global _SINK_IDS, _STATE

    os.makedirs(log_dir, exist_ok=True)

    # Drop every existing sink (including loguru's default stderr handler) and set a default
    # ``name`` extra so the format's {extra[name]} always resolves for un-bound records.
    logger.remove()
    logger.configure(extra={"name": app_name})

    ids: List[int] = []
    if console:
        ids.append(
            logger.add(
                sys.stderr,
                level=level,
                format=CONSOLE_FORMAT,
                backtrace=backtrace,
                diagnose=diagnose,
            )
        )
    if file:
        ids.append(
            logger.add(
                os.path.join(log_dir, f"{app_name}.log"),
                level=level,
                format=FILE_FORMAT,
                rotation="10 MB",
                retention="10 days",
                encoding="utf-8",
                enqueue=True,
                backtrace=backtrace,
                diagnose=diagnose,
            )
        )
    if json:
        ids.append(
            logger.add(
                os.path.join(log_dir, f"{app_name}.jsonl"),
                level=level,
                serialize=True,
                rotation="10 MB",
                retention="10 days",
                encoding="utf-8",
                enqueue=True,
            )
        )

    _SINK_IDS = ids
    _STATE = dict(
        app_name=app_name,
        log_dir=log_dir,
        console=console,
        file=file,
        json=json,
        backtrace=backtrace,
        diagnose=diagnose,
    )
    _install_intercept()
    return level


def set_global_level(level: Any) -> int:
    """Set the shared level. Reconfigures live sinks if logging has already been set up."""
    global _GLOBAL_LOG_LEVEL
    _GLOBAL_LOG_LEVEL = _resolve_log_level(level)
    if _STATE:
        _configure_sinks(level=_GLOBAL_LOG_LEVEL, **_STATE)
    return _GLOBAL_LOG_LEVEL


def get_logger(
    module_name: str,
    log_dir: str = "logs",
    level: Optional[int] = None,
    console_output: bool = True,
    file_output: bool = True,
    json_format: bool = False,
    colored_console: bool = True,
    max_file_size: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    rotation_type: str = "size",
    time_rotation: str = "midnight",
    custom_format: Optional[str] = None,
    filters: Optional[Any] = None,
    extra_handlers: Optional[List[logging.Handler]] = None,
) -> logging.Logger:
    """Return a stdlib :class:`logging.Logger` for ``module_name``.

    The returned logger is a thin handle: it carries no handlers of its own and funnels into
    loguru through the root :class:`InterceptHandler`. All output configuration (console/file/JSON,
    rotation, retention, colours) now lives centrally in :func:`setup_application_logging`, so the
    extra parameters below are accepted for backwards source-compatibility but are otherwise
    ignored. Prefer ``get_logger(__name__)``.
    """
    _ensure_intercept()
    log = logging.getLogger(module_name)
    if level is not None:
        log.setLevel(level)
    return log
