"""
Forwarding-rule schema version + migration registry.

The persisted shape of a rule lives nested in `guild_settings.rules[]`. To
evolve that shape without scattering `dict.get(..., default)` fallbacks across
every consumer, every rule carries a `schema_version` integer. Reads run the
rule through `migrate_rule` which advances missing-or-old docs to
`CURRENT_RULE_SCHEMA_VERSION`. Writes (`guild_manager.add_rule`,
`RuleSetupHelper.create_initial_rule`) stamp the current version up front so
fresh rules never need migrating.

## Adding a new schema version

1. Bump `CURRENT_RULE_SCHEMA_VERSION`.
2. Add a `_migrate_to_<N>(rule)` function that takes a rule at version N-1
   and returns it at version N. Treat the input as immutable; return a new
   dict or mutate-and-return — both are fine, callers expect the migrated
   dict back.
3. Register it in `_MIGRATIONS` keyed by the *target* version.
4. Lazy migration handles existing docs on read; the next `update_rule` /
   `add_rule` will persist the new shape. No manual backfill needed unless
   you depend on a queryable field landing in every doc immediately, in
   which case write a one-shot script.

## Versions

- v0 — pre-versioning. Any doc without `schema_version` is treated as v0.
- v1 — adds the `schema_version` field; otherwise structurally identical to
  v0.
- v2 — adds `settings.author_filters` with empty allow/deny lists for users
  + roles. Consumers can read the dict directly without `dict.get(..., {})`
  hedging.
- v3 — current. Reserves `destination_guild_id` (int) on the rule. Migration
  is a no-op stamp; the runtime path lazily backfills the field the first
  time it resolves the destination channel via `bot.get_channel`. Wizard-
  created rules at v3 stamp it directly at creation time.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict

logger = logging.getLogger(__name__)

CURRENT_RULE_SCHEMA_VERSION = 3

# Default author-filter shape stamped onto every rule at v2. Empty lists mean
# "no filter" — the runtime check in Forwarding.check_author_filters short-
# circuits when nothing is configured, so v2 rules behave like v1 rules until
# an admin populates a list.
DEFAULT_AUTHOR_FILTERS = {
    "allow_user_ids": [],
    "deny_user_ids": [],
    "allow_role_ids": [],
    "deny_role_ids": [],
}


def _migrate_to_1(rule: dict) -> dict:
    """v0 → v1: stamp the version. v0 docs are otherwise identical to v1."""
    rule["schema_version"] = 1
    return rule


def _migrate_to_2(rule: dict) -> dict:
    """v1 → v2: ensure ``settings.author_filters`` exists with default lists."""
    settings = rule.setdefault("settings", {})
    existing = settings.get("author_filters")
    if not isinstance(existing, dict):
        settings["author_filters"] = {k: list(v) for k, v in DEFAULT_AUTHOR_FILTERS.items()}
    else:
        # Backfill any missing list keys without clobbering admin-set values.
        for key, default in DEFAULT_AUTHOR_FILTERS.items():
            existing.setdefault(key, list(default))
    rule["schema_version"] = 2
    return rule


def _migrate_to_3(rule: dict) -> dict:
    """
    v2 → v3: reserve ``destination_guild_id``. The migration step itself only
    bumps the version; the runtime path in ``forward.py`` stamps the actual
    guild id the first time it resolves the destination channel. Wizard-
    created rules write the field directly at creation, skipping the lazy
    backfill.
    """
    rule.setdefault("destination_guild_id", None)
    rule["schema_version"] = 3
    return rule


# Migrations keyed by the *target* version. To go from v0 to v3, the loop in
# `migrate_rule` walks 1, 2, 3 in order.
_MIGRATIONS: Dict[int, Callable[[dict], dict]] = {
    1: _migrate_to_1,
    2: _migrate_to_2,
    3: _migrate_to_3,
}


def migrate_rule(rule: dict) -> dict:
    """
    Bring a single rule up to ``CURRENT_RULE_SCHEMA_VERSION``. Idempotent — a
    rule already at the current version returns unchanged. Errors in a single
    migration step are logged and the partially-migrated rule is returned so
    one bad doc can't block the rest of a guild's rules.
    """
    if not isinstance(rule, dict):
        return rule
    version = int(rule.get("schema_version", 0))
    while version < CURRENT_RULE_SCHEMA_VERSION:
        target = version + 1
        step = _MIGRATIONS.get(target)
        if step is None:
            logger.error(
                f"Missing migration for rule schema v{version} → v{target}; "
                "stamping current version to break the loop"
            )
            rule["schema_version"] = CURRENT_RULE_SCHEMA_VERSION
            break
        try:
            rule = step(rule)
        except Exception as e:
            logger.error(
                f"Rule schema migration v{version} → v{target} failed for rule "
                f"{rule.get('rule_id', '?')}: {e}",
                exc_info=True,
            )
            break
        version = int(rule.get("schema_version", target))
    return rule


def migrate_rules(rules: list) -> list:
    """Apply ``migrate_rule`` to every rule in a list. Pure convenience."""
    if not rules:
        return rules
    return [migrate_rule(r) for r in rules]
