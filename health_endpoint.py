# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""
Health Endpoint Module - centralized health-monitoring HTTP endpoint.

Bot-agnostic: the entrypoint passes the bot name / service label / port to
``initialize_health_server``. Every service exposes ``GET /health`` on its 500xx port
(see portsRules.md); HealthCheck polls it and classifies healthy / degraded / down from the
reported ``status`` (liveness is not correctness). Never leak internals here - the endpoint
is public.
"""

import http.server
import socketserver
import threading
import time
import logging
import json

logger = logging.getLogger(__name__)

_health_server = None
_start_time = time.time()


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for health check requests"""

    # Set by initialize_health_server().
    bot_instance = None
    db_manager = None
    bot_name = "Bot"
    service = "Discord bot"

    def do_GET(self):
        if self.path != '/health':
            self.send_response(404)
            self.end_headers()
            return

        status = "healthy"
        checks = {}
        gateway_latency_ms = None
        response = {
            "timestamp": time.time(),
            "bot": self.bot_name,
            "service": self.service,
            "uptime": int(time.time() - _start_time),
        }

        if self.bot_instance:
            try:
                connected = self.bot_instance.is_ready()
                response["discord_connected"] = connected
                response["guilds"] = len(self.bot_instance.guilds) if hasattr(self.bot_instance, 'guilds') else 0
                if hasattr(self.bot_instance, 'latency'):
                    gateway_latency_ms = round(self.bot_instance.latency * 1000, 2)
                response["latency_ms"] = gateway_latency_ms
                checks["discord"] = {
                    "status": "healthy" if connected else "unhealthy",
                    "latency_ms": gateway_latency_ms,
                }
                if not connected:
                    status = "degraded"
            except Exception as e:
                logger.warning(f"Failed to get bot status: {e}")
                response["discord_connected"] = False
                checks["discord"] = {"status": "unhealthy"}
                status = "degraded"
        else:
            response["discord_connected"] = False
            checks["discord"] = {"status": "unhealthy"}
            status = "degraded"

        # The db manager may be passed explicitly or hang off the bot. Prefer the richer
        # is_healthy probe and fall back to is_connected.
        db_manager = self.db_manager or getattr(self.bot_instance, "db_manager", None)
        if db_manager:
            try:
                healthy_attr = getattr(db_manager, "is_healthy", None)
                connected_attr = getattr(db_manager, "is_connected", None)
                if healthy_attr is not None:
                    db_ok = bool(healthy_attr() if callable(healthy_attr) else healthy_attr)
                elif connected_attr is not None:
                    db_ok = bool(connected_attr() if callable(connected_attr) else connected_attr)
                else:
                    db_ok = False
                response["database_connected"] = db_ok
                checks["database"] = {"status": "healthy" if db_ok else "unhealthy"}
                if not db_ok:
                    status = "degraded"
            except Exception as e:
                logger.warning(f"Failed to get database status: {e}")
                response["database_connected"] = False
                checks["database"] = {"status": "unhealthy"}
                status = "degraded"
        else:
            response["database_connected"] = False
            checks["database"] = {"status": "unhealthy"}
            status = "degraded"

        if gateway_latency_ms is not None:
            response["gateway_latency_ms"] = gateway_latency_ms
        response["checks"] = checks
        response["status"] = status
        # Degraded must return 200 so the monitor parses the body and renders
        # amber; non-200 is read as DOWN. Only hard-down returns 503.
        code = 503 if status == "unhealthy" else 200

        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, format, *args):
        """Disable default logging to reduce noise"""
        pass


def stop_health_server():
    """Shut down the health check server if running."""
    global _health_server
    if _health_server:
        _health_server.shutdown()
        _health_server.server_close()
        _health_server = None
        logger.info("Health check server stopped")


def initialize_health_server(port, bot=None, db_manager=None, bot_name="Bot", service="Discord bot"):
    """
    Initialize the health server in a background thread.

    Args:
        port (int): Port to listen on (the bot's 500xx health port).
        bot: Discord bot instance (optional).
        db_manager: Database manager instance (optional).
        bot_name (str): Human-readable bot name for the /health payload.
        service (str): Short service description for the /health payload.

    Returns:
        threading.Thread: The health server thread (or None on bind failure).
    """
    global _health_server

    HealthCheckHandler.bot_instance = bot
    HealthCheckHandler.db_manager = db_manager
    HealthCheckHandler.bot_name = bot_name
    HealthCheckHandler.service = service

    try:
        _health_server = ReusableTCPServer(("0.0.0.0", port), HealthCheckHandler)
    except Exception as e:
        logger.error(f"Failed to start health server on port {port}: {e}")
        return None

    health_thread = threading.Thread(target=_health_server.serve_forever, daemon=True, name="HealthCheckServer")
    health_thread.start()
    logger.info(f"Health check server running on port {port}")
    return health_thread
