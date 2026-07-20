# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Configuration + spec builder for the discord guild-snapshot layer.

Everything the legacy ``GuildCacheManager`` hardcoded lives here as tunable config: the
collection registry keys, the "dangerous"/"moderation" permission sets, the suspicious-member
threshold, the account-age buckets, the analytics timezone, and the freshness TTL. Defaults
reproduce the legacy behavior field-for-field (except the timezone default, which is now
``UTC`` rather than ``America/Chicago`` — set it explicitly if you want the old clock).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

from ..snapshots.spec import SnapshotSpec

# Registry keys the snapshot collections are declared under in the bot's define_collections.
DEFAULT_KEYS: Dict[str, str] = {
    "guild": "serverdata_guilds",
    "channels": "serverdata_channels",
    "roles": "serverdata_roles",
    "members": "serverdata_members",
    "analytics": "serverdata_analytics",
    "events": "serverdata_events",
}

# Permissions that flag a role as high-impact / moderation-capable (legacy defaults).
DANGEROUS_PERMISSIONS: Tuple[str, ...] = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "kick_members", "ban_members", "manage_messages", "mention_everyone",
)
MODERATION_PERMISSIONS: Tuple[str, ...] = (
    "kick_members", "ban_members", "manage_messages",
    "mute_members", "deafen_members", "move_members",
)

# (bucket label, inclusive upper bound in days). ``None`` upper bound = catch-all.
DEFAULT_AGE_BUCKETS: Tuple[Tuple[str, "int | None"], ...] = (
    ("0-7", 7), ("8-30", 30), ("31-90", 90), ("91+", None),
)


@dataclass
class GuildSnapshotConfig:
    """Tunables for :class:`~storage_engine.discord.service.GuildSnapshotService`."""

    timezone: str = "UTC"
    freshness_ttl: float = 3600.0
    dangerous_permissions: Tuple[str, ...] = DANGEROUS_PERMISSIONS
    moderation_permissions: Tuple[str, ...] = MODERATION_PERMISSIONS
    suspicious_new_account_days: int = 7
    age_buckets: Tuple[Tuple[str, "int | None"], ...] = DEFAULT_AGE_BUCKETS
    cache_version: str = "3.0"
    keys: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_KEYS))


def build_specs(keys: Dict[str, str]) -> list[SnapshotSpec]:
    """Build the five guild snapshot specs from a keys mapping.

    ``guild`` is the root (its ``updated_at`` drives freshness); ``members`` chunks at 1000.
    """
    return [
        SnapshotSpec("guild", keys["guild"], ("id",), "id", is_root=True),
        SnapshotSpec("channels", keys["channels"], ("guild_id", "id"), "guild_id"),
        SnapshotSpec("roles", keys["roles"], ("guild_id", "id"), "guild_id"),
        SnapshotSpec("members", keys["members"], ("guild_id", "id"), "guild_id", chunk_size=1000),
        SnapshotSpec("analytics", keys["analytics"], ("guild_id", "date"), "guild_id"),
    ]
