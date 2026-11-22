"""FastAPI application for the Stygian-Relay web dashboard."""

import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dashboard import db
from dashboard._engine.activity import activity_middleware, setup_dashboard_logging
from dashboard._engine.auth.csrf import csrf_endpoint, csrf_middleware
from dashboard._engine.auth.session import (
    ensure_oauth_state_ttl_index,
    ensure_session_ttl_index,
)
from dashboard._engine.auth.oauth import router as auth_router
from dashboard.config import CORS_ORIGINS, IS_PRODUCTION
from dashboard._engine.rate_limit import rate_limit_middleware
from dashboard.routers.dashboard import router as dashboard_router
from dashboard.routers.overview import router as overview_router
from dashboard.routers.rules import router as rules_router
from dashboard.routers.stats import router as stats_router
from dashboard.routers.premium import router as premium_router
from dashboard.routers.audit_log import router as audit_log_router
from dashboard.routers.settings import router as settings_router
from dashboard.routers.user_data import router as user_data_router
from status_push import start_status_push, stop_status_push

from storage.log import get_logger

# Configure the sinks before anything logs. Without this the process keeps
# loguru's default DEBUG handler and prints every library's debug output; with
# it the dashboard logs at INFO (LOG_LEVEL still wins) to console + logs/.
setup_dashboard_logging("dashboard-relay")

startup_logger = get_logger("dashboard.startup")
health_logger = get_logger("dashboard.health")

_frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "frontend", "dist"))
_frontend_public = os.path.abspath(os.path.join(os.path.dirname(__file__), "frontend", "public"))
_index_html = os.path.join(_frontend_dist, "index.html")
_START_TIME = time.time()

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: https://cdn.discordapp.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_logger.info(
        "Relay dashboard starting (production=%s)", IS_PRODUCTION
    )
    await db.connect()
    await ensure_oauth_state_ttl_index()
    await ensure_session_ttl_index()
    # The dashboard's own Uptime Kuma push monitor (the bot pushes its own). Off when unset.
    push_task = start_status_push(
        os.getenv("KUMA_PUSH_URL_DASHBOARD"), _status_verdict, label="Stygian-Relay dashboard",
    )
    yield
    # Before the databases close, so a redeploy never pushes "Database unavailable".
    await stop_status_push(push_task)
    await db.close()


# No public API docs in production (security review 2026-11-21, same as TheCodex):
# /docs, /redoc and /openapi.json listed every route for any anonymous visitor.
_docs = {} if not IS_PRODUCTION else {"docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(title="Stygian-Relay Dashboard", lifespan=lifespan, **_docs)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(csrf_middleware)
app.middleware("http")(rate_limit_middleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = _CSP
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# Registered last, so it is the outermost middleware and sees the final status -
# including the rate limiter's 429s and the CSRF check's 403s.
app.middleware("http")(activity_middleware)


app.add_api_route("/auth/csrf", csrf_endpoint, methods=["GET"])
app.include_router(auth_router, prefix="/auth")
app.include_router(dashboard_router, prefix="/api")
app.include_router(overview_router, prefix="/api")
app.include_router(rules_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(premium_router, prefix="/api")
app.include_router(audit_log_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(user_data_router, prefix="/api")


_PING_TIMEOUT_SECONDS = 3.0


async def _ping(get_client, label: str) -> float | None:
    """One bounded Mongo ping: its round trip in ms, or None when it failed.

    The failure is logged here, never returned in the body.
    """
    started = time.perf_counter()
    try:
        await asyncio.wait_for(get_client().admin.command("ping"), timeout=_PING_TIMEOUT_SECONDS)
        return round((time.perf_counter() - started) * 1000, 1)
    except Exception:
        health_logger.warning("%s Mongo health ping failed", label, exc_info=True)
        return None


async def _check() -> tuple[str, bool, bool, float | None]:
    """``(status, relay_ok, sessions_ok, relay_ping_ms)``, shared by /health and the Kuma push.

    The relay database is the dashboard's own data: without it no page can read or save
    anything, so a failure is ``unhealthy``. The shared sessions store is sign-in only:
    without it the public pages still load, so on its own it is ``degraded``.
    """
    relay_ms, sessions_ms = await asyncio.gather(
        _ping(db.relay_client, "Relay"),
        _ping(db.shared_client, "Shared-sessions"),
    )
    relay_ok, sessions_ok = relay_ms is not None, sessions_ms is not None
    status = "unhealthy" if not relay_ok else ("degraded" if not sessions_ok else "healthy")
    return status, relay_ok, sessions_ok, relay_ms


async def _status_verdict() -> tuple[str, str, float | None]:
    """``(status, message, ping_ms)`` for the dashboard's Uptime Kuma push monitor.

    The message is shown on the PUBLIC status page: plain words naming each failing check,
    "Online" when none fail. The ping is the round trip to the relay database.
    """
    status, relay_ok, sessions_ok, relay_ms = await _check()
    problems = []
    if not relay_ok:
        problems.append("Database unavailable")
    if not sessions_ok:
        problems.append("Sign-in unavailable")
    return status, ", ".join(problems) or "Online", relay_ms


@app.get("/health")
async def health():
    """Liveness plus both databases, per the fleet health contract (see ``_check``).

    ``unhealthy`` answers HTTP 503; ``degraded`` stays 200. The body carries statuses only.
    """
    status, relay_ok, sessions_ok, _ = await _check()
    response = {
        "status": status,
        "timestamp": time.time(),
        "service": "Stygian-Relay Dashboard",
        "uptime": int(time.time() - _START_TIME),
        "frontend_built": os.path.isfile(_index_html),
        "relay_db_connected": relay_ok,
        "shared_sessions_db_connected": sessions_ok,
        "checks": {
            "relay_db": {"status": "healthy" if relay_ok else "unhealthy"},
            "shared_sessions_db": {"status": "healthy" if sessions_ok else "unhealthy"},
        },
    }
    return JSONResponse(status_code=503 if status == "unhealthy" else 200, content=response)


if os.path.isdir(_frontend_dist):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(_frontend_dist, "assets")),
        name="assets",
    )


@app.get("/{path:path}")
async def spa_fallback(request: Request, path: str):
    if path and ".." not in path:
        for root in (_frontend_dist, _frontend_public):
            candidate = os.path.normpath(os.path.join(root, path))
            if candidate.startswith(root) and os.path.isfile(candidate):
                return FileResponse(candidate)
    if os.path.isfile(_index_html):
        return FileResponse(_index_html)
    return {"error": "Frontend not built. Run: cd dashboard/frontend && npm run build"}


if __name__ == "__main__":
    import uvicorn
    from dashboard.config import HOST, PORT

    # log_config=None leaves uvicorn's own loggers propagating into our loguru
    # sinks instead of installing a second, separately-formatted handler;
    # access_log=False because activity_middleware logs the same requests with
    # the actor and guild attached.
    uvicorn.run(
        "dashboard.app:app",
        host=HOST,
        port=PORT,
        reload=not IS_PRODUCTION,
        log_config=None,
        access_log=False,
    )
