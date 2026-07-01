# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""storage_engine.config — the shared Guild Configuration Engine.

A dict-level, guild-scoped config store generalized from EcomRebuild's
``storage/config_manager.py`` (the most advanced sibling: dotted-path ``update``,
``_extra`` catch-all, change-stream coherency). The engine standardizes *persistence,
caching, and CRUD* around a guild config document; the bot keeps its own typed
``GuildConfig`` dataclass, feature layout, and schema-version migration — those stay
bot-owned (see ``guild_config_reference.py``).

``GuildConfigStore`` reads hit-first through the ``CollectionManager`` it is given, so
it shares the manager's pluggable cache and the engine's ``ChangeStreamWatcher`` (list
the config collection in ``bindings.WATCHED_COLLECTIONS`` for real-time invalidation).
``guild_id`` is normalized to ``str`` at every boundary; ``migration`` ships the one-time
int→str document sweep for bots that stored it as an int.
"""

from .guild_config_store import GuildConfigStore
from .migration import normalize_guild_id_to_str

__all__ = ["GuildConfigStore", "normalize_guild_id_to_str"]
