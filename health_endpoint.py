"""
Health Endpoint Module for Stygian-Relay Bot
Provides HTTP endpoint for centralized health monitoring

Port: 50013
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

    bot_instance = None
    db_manager = None

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
            "bot": "Stygian-Relay",
            "service": "Discord Message Forwarding Bot",
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

        if self.db_manager:
            try:
                healthy_attr = getattr(self.db_manager, "is_healthy", None)
                connected_attr = getattr(self.db_manager, "is_connected", None)
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


def initialize_health_server(port=50013, bot=None, db_manager=None):
    """
    Initialize the health server in a background thread

    Args:
        port (int): Port to listen on (default: 50013)
        bot: Discord bot instance (optional)
        db_manager: Database manager instance (optional)

    Returns:
        threading.Thread: The health server thread
    """
    global _health_server

    HealthCheckHandler.bot_instance = bot
    HealthCheckHandler.db_manager = db_manager

    try:
        _health_server = ReusableTCPServer(("0.0.0.0", port), HealthCheckHandler)
    except Exception as e:
        logger.error(f"Failed to start health server on port {port}: {e}")
        return None

    health_thread = threading.Thread(target=_health_server.serve_forever, daemon=True, name="HealthCheckServer")
    health_thread.start()
    logger.info(f"Health check server running on port {port}")
    return health_thread
