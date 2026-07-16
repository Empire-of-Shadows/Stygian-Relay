# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Relay premium domain layer (master-owned; per-guild now, per-user future-proofed).

Entitlement-backed premium: raw ``entitlements`` records fold into a fast-read
``premium_state`` doc per scope. The concrete singleton is wired in the package facade
(``storage/bot_specific/relay/__init__.py``) so callers do:

    from storage.bot_specific.relay import premium_manager

The per-bot SKU map + settings live in the cog's ``premium/settings`` seam, not here - this
module is bot-agnostic.
"""

from .constants import (
    SCOPE_GUILD,
    SCOPE_USER,
    SOURCE_EVENT,
    SOURCE_INTERACTION,
    SOURCE_MANUAL,
    SOURCE_RECONCILE,
    TIER_FREE,
    TIER_UNKNOWN,
)
from .premium_manager import PremiumManager
from .state import PremiumState, compute_state, entitlement_is_active

__all__ = [
    "PremiumManager",
    "PremiumState",
    "compute_state",
    "entitlement_is_active",
    "SCOPE_GUILD",
    "SCOPE_USER",
    "SOURCE_EVENT",
    "SOURCE_RECONCILE",
    "SOURCE_INTERACTION",
    "SOURCE_MANUAL",
    "TIER_FREE",
    "TIER_UNKNOWN",
]
