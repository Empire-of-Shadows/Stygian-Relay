# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""storage_engine.services — generic, config-driven storage capabilities.

Reusable storage managers promoted from code that was duplicated across bots, made
bot-agnostic by injecting collection keys / field maps / TTLs / predicates instead of
hard-coding them. Each is vendored byte-identical into every bot; the per-bot difference is
data, not code.

| Capability | Class | Promoted from |
|---|---|---|
| Audit log writer | ``AuditLog`` | TheHost/Ecom ``storage/audit_log.py`` |
| Cached setup/requirement gate | ``SetupGate`` | TheHost ``storage/setup_gatekeeper.py`` (storage half) |
| Single-instance advisory lock | ``SingletonLock`` | TheHost ``storage/instance_lock.py`` |
| User preference / opt-out cache | ``UserPreferenceCache`` | TheHost ``storage/user_privacy.py`` |

These deliberately carry NO discord dependency — discord-facing UI (embeds, permission checks)
stays in the bot. ``grep "Capability:"`` across the engine to discover the full surface.
"""

from .audit_log import AuditLog
from .setup_gate import SetupGate
from .singleton_lock import SingletonLock
from .user_preference_cache import UserPreferenceCache

__all__ = ["AuditLog", "SetupGate", "SingletonLock", "UserPreferenceCache"]
