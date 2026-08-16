# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""Service-to-service IPC for the fleet - one place for every internal call.

Two bots that need to talk do it HERE and nowhere else. Outbound calls go through
``ipc.get_client()``; inbound work is a capability file under
``ipc/capabilities/``. Nothing else in a bot opens an HTTP connection to a
sibling service, so the whole cross-service surface of a bot is one directory
you can read in a sitting.

Layout inside a bot (this package, vendored + seam)::

    ipc/
      _engine/          VENDORED from EmpireSystems/runtime_engine/ipc/_engine
      settings/         SEAM: bindings.py - who am I, where are my peers
      capabilities/     SEAM: one file per capability this bot PROVIDES

The transport is HTTP over the ``obsidian_grid`` docker network, on the bot's
``510NN`` IPC port from ``portsRules.md``. That port is deliberately NOT
published to the host - only containers on the shared network can reach it, and
even then a request needs the shared secret. The public ``500NN`` health
endpoint stays exactly what it is: unauthenticated, read-only, and separate.

Why HTTP and not a unix socket, given every bot runs on one machine: containers
have separate network namespaces, so a socket means a shared bind mount and a
filesystem coupling that breaks the day a service moves hosts. A local HTTP
round trip costs a couple of milliseconds against a 3-second Discord
interaction budget, ``aiohttp`` is already present as a discord.py dependency,
and the result is debuggable with curl from inside any container. If a socket is
ever wanted, aiohttp speaks one on both ends and the change is confined to the
bindings seam - the protocol does not move.
"""

from ._engine.client import IpcClient, close_client, get_client
from ._engine.protocol import (
    Capability,
    CapabilityContext,
    IpcResult,
    ParamSpec,
    Reason,
    is_engine_code,
    ok,
    reject,
)
from ._engine.registry import REGISTRY, load_registry
from ._engine.server import start_ipc_server, stop_ipc_server

__all__ = [
    "Capability",
    "CapabilityContext",
    "IpcClient",
    "IpcResult",
    "ParamSpec",
    "REGISTRY",
    "Reason",
    "close_client",
    "get_client",
    "is_engine_code",
    "load_registry",
    "ok",
    "reject",
    "start_ipc_server",
    "stop_ipc_server",
]
