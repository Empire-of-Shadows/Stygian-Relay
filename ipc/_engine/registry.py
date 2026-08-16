# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""Capability discovery: what this bot will do for other services.

Handlers are DISCOVERED, not listed. Every module in the bot's own
``ipc/capabilities/`` package that exposes a module-level ``CAPABILITIES`` tuple
contributes its handlers, in module-name order. Offering a new capability is one
new file in that directory - no registration list, no import to remember.

This is the same discovery shape as the shop's fulfilment registry and the
achievement condition registry, on purpose: the fleet has one way of saying
"drop a file in this folder and it is live", and a third spelling of it would be
a thing to learn for no reason.

Discovery failures are LOUD. A capability module that fails to import is a
capability another service is about to call and will not find, so it is logged
at error with the traceback rather than swallowed.

A bot that provides nothing has no ``ipc/capabilities/`` package at all. That is
normal - a pure consumer (a bot that only makes calls) never starts a server -
and it is not an error.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Dict, List, Optional

from storage.log import get_logger

from .protocol import Capability

logger = get_logger("IPC")

# The bot-owned seam package this engine imports handlers from.
_SEAM_PACKAGE = "ipc.capabilities"


def _discover() -> List[Capability]:
    """Import every capability module in the bot's seam and collect its handlers."""
    try:
        package = importlib.import_module(_SEAM_PACKAGE)
    except ModuleNotFoundError:
        logger.debug(f"No {_SEAM_PACKAGE} package - this bot provides no IPC capabilities")
        return []
    except Exception:
        logger.exception(f"{_SEAM_PACKAGE} failed to import - this bot will provide NOTHING")
        return []

    found: List[Capability] = []
    for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
        if module_info.name.startswith("_"):
            continue
        full_name = f"{_SEAM_PACKAGE}.{module_info.name}"
        try:
            module = importlib.import_module(full_name)
        except Exception:
            logger.exception(
                f"Capability module {full_name!r} failed to import - "
                f"the capabilities it declares will NOT be callable"
            )
            continue
        handlers = getattr(module, "CAPABILITIES", None)
        if not handlers:
            continue
        for handler in handlers:
            if not isinstance(handler, Capability):
                logger.error(
                    f"{full_name}.CAPABILITIES contains {handler!r}, which is not a "
                    f"Capability - skipped"
                )
                continue
            if not handler.key:
                logger.error(f"{full_name} exposes a capability with no key - skipped")
                continue
            found.append(handler)
    return found


class CapabilityRegistry:
    """Immutable lookup of capability handlers, keyed by their dotted key."""

    def __init__(self, handlers: List[Capability]):
        self._by_key: Dict[str, Capability] = {}
        for handler in handlers:
            if handler.key in self._by_key:
                logger.error(f"Duplicate IPC capability {handler.key!r}; keeping the first")
                continue
            self._by_key[handler.key] = handler

    def get(self, key: str) -> Optional[Capability]:
        return self._by_key.get(key)

    def keys(self) -> List[str]:
        return sorted(self._by_key)

    def __len__(self) -> int:
        return len(self._by_key)

    def catalogue(self) -> List[dict]:
        """Payload for the discovery endpoint, sorted for a stable admin UI."""
        return [self._by_key[key].metadata() for key in sorted(self._by_key)]


_registry: Optional[CapabilityRegistry] = None


def load_registry(*, refresh: bool = False) -> CapabilityRegistry:
    """Build (once) and return this bot's capability registry.

    Discovery is deferred rather than done at import time because a capability
    reaches into the bot's own domain layer, which is not importable until the
    bot's packages are on the path. The server calls this at start.
    """
    global _registry
    if _registry is None or refresh:
        _registry = CapabilityRegistry(_discover())
    return _registry


class _LazyRegistry:
    """Module-level ``REGISTRY`` that builds itself on first real use."""

    def __getattr__(self, name):
        return getattr(load_registry(), name)

    def __len__(self) -> int:
        return len(load_registry())


REGISTRY = _LazyRegistry()

__all__ = ["REGISTRY", "CapabilityRegistry", "load_registry"]
