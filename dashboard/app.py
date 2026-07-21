"""FastAPI application for the Stygian-Relay web dashboard."""

import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dashboard import db
from dashboard._engine.auth.csrf import csrf_endpoint, csrf_middleware
from dashboard._engine.auth.session import (
    ensure_oauth_state_ttl_index,
    ensure_session_ttl_index,
)
from dashboard._engine.auth.oauth import router as auth_router
from dashboard.config import CORS_ORIGINS, IS_PRODUCTION
from dashboard._engine.rate_limit import rate_limit_middleware
from dashboard.routers.dashboard import router as dashboard_router
from dashboard.routers.rules import router as rules_router
from dashboard.routers.stats import router as stats_router
from dashboard.routers.premium import router as premium_router
from dashboard.routers.audit_log import router as audit_log_router
from dashboard.routers.settings import router as settings_router

import logging

startup_logger = logging.getLogger("dashboard.startup")
health_logger = logging.getLogger("dashboard.health")

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
    yield
    await db.close()


app = FastAPI(title="Stygian-Relay Dashboard", lifespan=lifespan)

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


app.add_api_route("/auth/csrf", csrf_endpoint, methods=["GET"])
app.include_router(auth_router, prefix="/auth")
app.include_router(dashboard_router, prefix="/api")
app.include_router(rules_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(premium_router, prefix="/api")
app.include_router(audit_log_router, prefix="/api")
app.include_router(settings_router, prefix="/api")


@app.get("/health")
async def health():
    response = {
        "status": "healthy",
        "timestamp": time.time(),
        "service": "Stygian-Relay Dashboard",
        "uptime": int(time.time() - _START_TIME),
        "frontend_built": os.path.isfile(_index_html),
    }
    checks: dict = {}

    try:
        await db.relay_client().admin.command("ping")
        response["relay_db_connected"] = True
        checks["relay_db"] = {"status": "healthy"}
    except Exception:
        health_logger.warning("Relay Mongo health ping failed", exc_info=True)
        response["relay_db_connected"] = False
        checks["relay_db"] = {"status": "unhealthy"}
        response["status"] = "degraded"

    try:
        await db.shared_client().admin.command("ping")
        response["shared_sessions_db_connected"] = True
        checks["shared_sessions_db"] = {"status": "healthy"}
    except Exception:
        health_logger.warning("Shared-sessions Mongo health ping failed", exc_info=True)
        response["shared_sessions_db_connected"] = False
        checks["shared_sessions_db"] = {"status": "unhealthy"}
        response["status"] = "degraded"

    response["checks"] = checks
    return response


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

    uvicorn.run("dashboard.app:app", host=HOST, port=PORT, reload=not IS_PRODUCTION)
