# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""storage_engine.interaction — Discord interaction / component state.

One polymorphic store mapping a Discord ``message_id`` to the feature context needed to
service its button/select interactions (``InteractionStateStore``), plus a tiny
``custom_id`` codec for the ``feature:action:target`` routing convention.

This consolidates the per-feature ``message_id → context`` collections that recur across
the bots (TheCodex WYR ``daily_wyr_mappings``, suggestions, Relay forwarding logs): one
TTL-indexed collection, hit-first cached lookups (button handlers are high-frequency), and
a ``iter_active`` helper to re-register persistent views on startup.

Genuinely feature-specific state (in-memory game sessions, guide page-tree navigation) is
intentionally out of scope — see ``docs/storage_engine/interaction-state.md``.
"""

from .custom_id import pack, parse, CustomId
from .state_store import InteractionStateStore

__all__ = ["InteractionStateStore", "pack", "parse", "CustomId"]
