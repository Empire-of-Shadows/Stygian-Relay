# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Stygian-Relay admin audit trail (writes the ``audit_logs`` collection).

Name-collides with the engine's generic ``storage_engine/services/audit_log.py`` -- that is the
promotion signal firing on purpose. Evaluated and NOT promoted: relay's
``AuditLog.log(category, guild_id, actor_id, action, payload)`` is a bespoke signature that
relay's admin bindings already adapt to. Combining the two is real work, not a rename.
"""

from .writer import AuditLog

__all__ = ["AuditLog"]
