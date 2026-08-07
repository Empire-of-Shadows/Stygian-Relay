# VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
# Edit the master at EmpireSystems/dashboard_engine/ and run:
#     python EmpireSystems/tools/sync_dashboard_engine.py
# Drift is enforced by:
#     python EmpireSystems/tools/sync_dashboard_engine.py --check
"""Dashboard process logging: sink setup, plus one line per meaningful request.

None of the dashboards configured logging at all. The first ``get_logger`` call
installs the stdlib -> loguru intercept at level 0 while loguru still holds its
default DEBUG stderr sink, so every debug record from every library reached the
console: the dashboards were effectively running in debug mode, and the useful
signal (who changed what) was not being logged at all.

This module supplies both halves of the fix.

``setup_dashboard_logging`` is the call the dashboards were missing - the web
process equivalent of the bot's ``setup_application_logging``. It pins the level
to INFO (``LOG_LEVEL`` still wins if a deployment really wants DEBUG), installs
the console + rotating file + JSON sinks, and quiets the chatty HTTP/driver
loggers that produced most of the noise.

``activity_middleware`` supplies what that noise was standing in for: a readable
record of who did what. Every mutating API call, every auth event and every
failure logs one INFO line naming the actor, the action, the guild, the outcome
and how long it took. Successful reads log at DEBUG so routine SPA polling does
not bury them; set ``DASHBOARD_LOG_READS=1`` to include reads as well.

Wiring, in a bot's ``dashboard/app.py``::

    setup_dashboard_logging("codex-dashboard")
    ...
    app.middleware("http")(activity_middleware)   # register LAST = outermost

and in the bot's ``dashboard/auth/dependencies.py``, so the line can name a
person instead of an IP::

    async def get_current_user(request: Request, ...):
        ...
        record_actor(request, session)
        return session
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import Request

from dashboard import config as _config

logger = logging.getLogger("dashboard.activity")

# Third-party loggers that are chatty at DEBUG/INFO and say nothing about what a
# person did. ``uvicorn.access`` is in the list because activity_middleware
# replaces it with a line that actually names the actor and the guild.
_QUIET_LOGGERS = (
    "uvicorn.access",
    "httpx",
    "httpcore",
    "multipart",
    "python_multipart",
    "watchfiles",
    "asyncio",
    "pymongo",
    "motor",
)

# Never logged: liveness polling and static asset serving would drown everything
# else. ``/auth/csrf`` is a token fetch the SPA repeats, not a user action.
_IGNORED_PREFIXES = ("/health", "/assets/", "/auth/csrf", "/favicon")

# Only the API and auth surfaces are activity; everything else is the SPA shell.
_TRACKED_PREFIXES = ("/api/", "/auth/")

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Reverse proxies whose X-Forwarded-For may be trusted for client-IP resolution
# (same OPTIONAL seam value the rate limiter uses). Without it we log the socket
# peer, which behind a proxy is the proxy - correct, if less useful, and never
# attacker-controlled.
_TRUSTED_PROXIES = frozenset(getattr(_config, "TRUSTED_PROXY_IPS", ()) or ())

# Promote successful reads from DEBUG to INFO. Off by default: a dashboard page
# fires many GETs, and at INFO they crowd out the writes. Importing
# ``dashboard.config`` above has already loaded the env file.
_read_flag = getattr(_config, "DASHBOARD_LOG_READS", None)
if _read_flag is None:
    _read_flag = os.getenv("DASHBOARD_LOG_READS", "")
_LOG_READS = str(_read_flag).strip().lower() in {"1", "true", "yes", "on"}


def setup_dashboard_logging(app_name: str, log_dir: str = "logs") -> None:
    """Configure this process's log sinks at INFO and silence the noisy libraries.

    Call once, at import time in ``dashboard/app.py``, before the app serves.
    ``LOG_LEVEL`` in the environment still wins, so a deployment can opt back
    into DEBUG for a debugging session without a code change.

    :param app_name: Names the log files (``logs/{app_name}.log`` / ``.jsonl``).
    :param log_dir: Directory for those files; created if absent.
    """
    from storage.log import setup_application_logging

    setup_application_logging(app_name, log_level=logging.INFO, log_dir=log_dir)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def record_actor(request: Request, session: dict) -> None:
    """Remember who this request belongs to so ``activity_middleware`` can name them.

    Called from the bot's ``get_current_user`` dependency, which has already
    resolved the session. Stored on ``request.state``, which is backed by the
    ASGI scope and so is visible to the middleware wrapping the request.
    """
    user = session.get("user_data") or {}
    request.state.actor = (
        str(user.get("id") or session.get("user_id") or "?"),
        user.get("global_name") or user.get("username") or "unknown",
    )


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer in _TRUSTED_PROXIES:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer


def _is_tracked(path: str) -> bool:
    if path.startswith(_IGNORED_PREFIXES):
        return False
    return path.startswith(_TRACKED_PREFIXES)


def _action(request: Request) -> str:
    """The handler's name (``update_section``, ``logout``, ...) - the *what* of the line.

    The router writes ``endpoint`` into the scope before the handler runs, and
    the middleware shares that scope, so it is set by the time we log. Requests
    that never matched a route (a 404) have no endpoint and read "unmatched";
    the path is on the line either way.
    """
    endpoint = request.scope.get("endpoint")
    return getattr(endpoint, "__name__", None) or "unmatched"


def _level_for(request: Request, status: int) -> int:
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    # Logins and logouts are activity even though they are GETs.
    if request.url.path.startswith("/auth/"):
        return logging.INFO
    if request.method in _READ_METHODS and not _LOG_READS:
        return logging.DEBUG
    return logging.INFO


def _emit(request: Request, status: int, elapsed_ms: float, failed: bool = False) -> None:
    user_id, user_name = getattr(request.state, "actor", None) or ("-", "anonymous")
    guild_id = (request.scope.get("path_params") or {}).get("guild_id", "-")
    logger.log(
        _level_for(request, status),
        "%s %s -> %d in %dms | action=%s user=%s(%s) guild=%s ip=%s",
        request.method,
        request.url.path,
        status,
        elapsed_ms,
        _action(request),
        user_name,
        user_id,
        guild_id,
        _client_ip(request),
        exc_info=failed,
    )


async def activity_middleware(request: Request, call_next):
    """Log one line per API/auth request: actor, action, guild, outcome, duration.

    Register it LAST so it is the outermost middleware and therefore sees the
    final status - including the 429s the rate limiter returns and the 403s the
    CSRF check returns, which are exactly the ones worth having in the log.
    """
    if not _is_tracked(request.url.path):
        return await call_next(request)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # ServerErrorMiddleware sits outside us and turns this into the 500 the
        # client sees; log it as ours before letting it through.
        _safe_emit(request, 500, (time.perf_counter() - started) * 1000, failed=True)
        raise
    _safe_emit(request, response.status_code, (time.perf_counter() - started) * 1000)
    return response


def _safe_emit(request: Request, status: int, elapsed_ms: float, failed: bool = False) -> None:
    """Never let a logging problem turn a working request into a failed one."""
    try:
        _emit(request, status, elapsed_ms, failed=failed)
    except Exception:  # pragma: no cover - defensive
        logger.warning("Activity logging failed for %s", request.url.path, exc_info=True)
