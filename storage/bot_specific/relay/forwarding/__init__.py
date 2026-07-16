# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Stygian-Relay message-forwarding rules: schema version + migration registry."""

from .rule_schema import CURRENT_RULE_SCHEMA_VERSION, migrate_rule, migrate_rules

__all__ = ["CURRENT_RULE_SCHEMA_VERSION", "migrate_rule", "migrate_rules"]
