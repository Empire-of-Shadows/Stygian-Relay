"""storage_engine bindings — Stygian-Relay (bot-owned).

The single integration point between the installed ``storage_engine`` package and relay's
environment. The engine reads these names by name. Everything under ``storage/`` is now bot-owned
seam (``bindings.py`` / ``define_collections.py`` / ``manager.py`` + ``storage/bot_specific/relay/``);
the engine itself is installed, not vendored here.

Template: ``EmpireSystems/Settings/storage/bindings_reference.py``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# The storage engine installs as the ``storage_engine`` package — import it absolutely.
from storage_engine.cache.backend import CacheBackend
from storage_engine.cache.local import LocalCache

# Relay's entrypoint (Relay.py) loads docker/.env (+ .env.local override) before use, but
# bindings is imported as soon as ``storage.manager`` is first touched — which can precede the
# entrypoint's own load (e.g. when a cog module is imported first). Load here too so the URI is
# always present. (Idempotent: load_dotenv() only fills unset keys unless override=True.)
_env_dir = Path(__file__).resolve().parent.parent / "docker"
if (_env_dir / ".env").exists():
    load_dotenv(_env_dir / ".env")
else:
    load_dotenv()
load_dotenv(_env_dir / ".env.local", override=True)


# ── Connections (ENGINE CONTRACT: MONGO_URIS) ──────────────────────────────────
# Relay uses a single primary connection. NOTE: relay's env var is MONGODB_URI (not MONGO_URI).
MONGO_URIS: Dict[str, Optional[str]] = {
    "primary": os.getenv("MONGODB_URI"),
}


# ── Cache defaults (ENGINE CONTRACT: CACHE_DEFAULTS) ────────────────────────────
CACHE_DEFAULTS: Dict[str, Any] = {
    "max_size": 5000,
    "default_ttl": 300,
}


# ── Cache backend factory (ENGINE CONTRACT: build_cache) ────────────────────────
def build_cache() -> CacheBackend:
    """Return the cache backend this bot uses (in-process LocalCache)."""
    return LocalCache(**CACHE_DEFAULTS)


# ── Change-stream coherency (ENGINE CONTRACT: WATCHED_COLLECTIONS) ──────────────
# Relay has no external writer to its collections (no dashboard yet), so TTL-only coherency is
# correct and avoids requiring change streams. (Relay's GuildManager keeps its own short-TTL
# caches and invalidates them on its own writes.)
WATCHED_COLLECTIONS: List[str] = []


# ── Audit hook (ENGINE CONTRACT: audit_storage_event) — OPTIONAL ────────────────
async def audit_storage_event(
    *,
    collection: str,
    action: str,
    query: dict,
    actor_id: Optional[int] = None,
) -> None:
    """No-op: relay audits through ``storage/bot_specific/relay/audit.py``."""
    return None
