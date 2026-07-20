# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Stygian-Relay guild-settings feature.

Deliberately docstring-only: do NOT import ``permissions`` here. ``bot_specific/relay/__init__``
rebinds ``guild_manager`` from the module to the constructed instance, and ``permissions``
reads that instance via ``from .. import guild_manager``. Importing permissions from here
would re-enter ``bot_specific.relay`` while it is still initializing and raise ImportError.
Import the modules directly instead (``from .guild.guild_manager import GuildManager``).
"""
