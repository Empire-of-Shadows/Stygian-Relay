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
import re
import sys
from typing import Any, Callable, List, Optional, Union

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

# ── Console colour behaviour (opt-in via env; files are never coloured) ──────
#
# loguru only colourizes when the sink is a TTY, and inside a Docker container
# stdout/stderr never is one - so production logs viewed over SSH render flat.
# ``LOG_COLOR`` overrides the autodetect for the CONSOLE sink only:
#   force / always / true / 1  -> colourize even without a TTY (docker logs
#                                 pass ANSI through; modern terminals render it)
#   off / never / false / 0    -> never colourize
#   auto / unset               -> today's behaviour (TTY autodetect)
#
# ``LOG_HIGHLIGHT=true`` additionally paints the fleet's structured log tokens
# inside the message itself - G:/U:/C: ids and +N XP / +N Embers amounts - so a
# payout line breaks into scannable chunks. Purely cosmetic, console-only, and
# any formatting error falls back to the plain format for that record.

_TOKEN_PATTERNS: List[tuple] = [
    (re.compile(r"\bG:\d+"), "yellow"),
    (re.compile(r"\bU:\d+"), "light-blue"),
    (re.compile(r"\bC:\d+"), "light-cyan"),
    (re.compile(r"\+[\d,]+ XP\b"), "light-green"),
    (re.compile(r"\+[\d,]+ Embers\b"), "light-yellow"),
]

# Highlight mode also colours the ``module:function:line`` segment by the
# FEATURE that emitted the record (first case-insensitive substring match on
# the logger name, order matters), so features separate at a glance in a mixed
# tail. The table carries the whole fleet's vocabulary - each bot only ever
# matches its own module paths, so entries from other bots are inert. A bot
# can override or extend it without code via ``LOG_SOURCE_COLORS`` in its env:
# ``keyword:color,keyword:color`` - env entries win over this table, and color
# names are validated against loguru's palette so a typo can never break the
# sink. Anything unmatched keeps the engine's usual cyan.
_SOURCE_COLORS: List[tuple] = [
    # Ecom (economy / leveling)
    ("voice", "blue"),
    ("reaction", "magenta"),
    ("achievement", "yellow"),
    ("prestige", "light-red"),
    ("shop", "light-green"),
    ("trade", "light-green"),
    ("notification", "light-magenta"),
    # TheHost (games)
    ("uno", "light-red"),
    ("hangman", "light-green"),
    ("tictactoe", "light-blue"),
    ("counting", "green"),
    ("milestone", "yellow"),
    ("leaderboard", "light-magenta"),
    # TheCodex
    ("drop", "light-blue"),
    ("wyr", "magenta"),
    ("suggestion", "light-green"),
    ("guide", "green"),
    ("greeting", "light-magenta"),
    ("member", "light-magenta"),
    ("embed", "yellow"),
    ("tracker", "light-cyan"),
    # TheDecree
    ("quote", "magenta"),
    ("scheduler", "blue"),
    ("claim", "light-blue"),
    # ImperialReminder
    ("bump", "green"),
    ("time_handler", "blue"),
    ("timer", "blue"),
    # Stygian-Relay
    ("forward", "green"),
    # Shared subsystems
    ("premium", "light-yellow"),
    ("ipc", "light-cyan"),
    # Generic catch-alls last, so the specific families above win.
    ("message", "green"),
]
_SOURCE_DEFAULT_COLOR = "cyan"

# loguru's colour palette - the only names LOG_SOURCE_COLORS may use.
_VALID_COLORS = frozenset(
    ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
    + ["light-" + c for c in ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")]
)

# Resolved at sink-configure time: env overrides first, then the fleet table.
_ACTIVE_SOURCE_COLORS: List[tuple] = list(_SOURCE_COLORS)


def _env_source_colors() -> List[tuple]:
    """Parse LOG_SOURCE_COLORS (``keyword:color,...``); invalid entries dropped."""
    out: List[tuple] = []
    for part in (os.getenv("LOG_SOURCE_COLORS") or "").split(","):
        keyword, _, color = part.partition(":")
        keyword, color = keyword.strip().lower(), color.strip().lower()
        if keyword and color in _VALID_COLORS:
            out.append((keyword, color))
    return out


def _resolve_source_colors() -> None:
    global _ACTIVE_SOURCE_COLORS
    _ACTIVE_SOURCE_COLORS = _env_source_colors() + _SOURCE_COLORS

# Level colours applied at sink setup (console rendering only - markup is
# stripped wherever colourize is off, and files never colourize). WARNING
# (yellow) and ERROR (red) keep loguru's defaults; INFO gains green and DEBUG
# blue so levels separate on a scan.
_LEVEL_COLORS = {
    "INFO": "<green><bold>",
    "DEBUG": "<blue>",
}

def _apply_level_colors() -> None:
    for level_name, color in _LEVEL_COLORS.items():
        try:
            logger.level(level_name, color=color)
        except Exception:
            # A level colour is cosmetic; never let it break sink setup.
            pass


def _source_color(logger_name: str) -> str:
    lowered = logger_name.lower()
    for key, color in _ACTIVE_SOURCE_COLORS:
        if key in lowered:
            return color
    return _SOURCE_DEFAULT_COLOR


def _console_colorize() -> Optional[bool]:
    """Resolve LOG_COLOR: True (force), False (off), or None (TTY autodetect)."""
    value = (os.getenv("LOG_COLOR") or "auto").strip().lower()
    if value in ("force", "always", "true", "1", "yes", "on"):
        return True
    if value in ("off", "never", "false", "0", "no"):
        return False
    return None


def _highlight_enabled() -> bool:
    return (os.getenv("LOG_HIGHLIGHT") or "").strip().lower() in ("1", "true", "yes", "on")


def _highlighted_console_format(record: dict) -> str:
    """Dynamic console format that wraps known tokens in colour markup.

    The message text is embedded literally into the returned format string, so
    braces are doubled and ``<`` escaped first (or loguru would parse stray
    markup out of user content); the colour tags injected AFTER that escaping
    are the only markup loguru sees. When format is a callable, loguru appends
    neither the newline nor the exception - both are included explicitly.
    """
    try:
        msg = record["message"].replace("{", "{{").replace("}", "}}").replace("<", r"\<")
        for pattern, color in _TOKEN_PATTERNS:
            msg = pattern.sub(lambda m, c=color: f"<{c}>{m.group(0)}</{c}>", msg)
        src = _source_color(str(record["extra"].get("name", "")))
        prefix = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            f"<{src}>{{extra[name]}}</{src}>:<{src}>{{function}}</{src}>:"
            f"<{src}>{{line}}</{src}> - "
        )
        return prefix + msg + "\n{exception}"
    except Exception:
        return CONSOLE_FORMAT + "\n{exception}"

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

    The standard loguru bridge: every record emitted through the stdlib - our ``get_logger``
    loggers as well as third-party libraries - is re-emitted through loguru so it inherits the
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
    _apply_level_colors()
    _resolve_source_colors()

    ids: List[int] = []
    if console:
        console_format: Union[str, Callable] = CONSOLE_FORMAT
        if _highlight_enabled():
            console_format = _highlighted_console_format
        console_kwargs: dict = {}
        colorize = _console_colorize()
        if colorize is not None:
            console_kwargs["colorize"] = colorize
        ids.append(
            logger.add(
                sys.stderr,
                level=level,
                format=console_format,
                backtrace=backtrace,
                diagnose=diagnose,
                **console_kwargs,
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


def get_logger(module_name: str, level: Optional[int] = None) -> logging.Logger:
    """Return a stdlib :class:`logging.Logger` for ``module_name``.

    A thin handle: it carries no handlers of its own and funnels into loguru through the root
    :class:`InterceptHandler`. All output configuration (console/file/JSON, rotation, retention,
    colours) lives centrally in :func:`setup_application_logging`. Prefer ``get_logger(__name__)``.
    """
    _ensure_intercept()
    log = logging.getLogger(module_name)
    if level is not None:
        log.setLevel(level)
    return log
