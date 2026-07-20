# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Bot-specific engine code, namespaced by bot.

Master-owned and vendored into ONLY the bot it is named for. Such code still reaches MongoDB
through the generic engine (``db_manager`` / ``CollectionManager``), so every bot reads and
writes the same way.

It lives here, rather than in the bot, so every feature in the ecosystem is visible in one
tree. Group each bot's code by FEATURE (``<bot>/<feature>/``): when a feature directory name
turns up under a second bot, that is the signal to evaluate promoting it into the generic
engine. Promote only if the feature can genuinely be combined to work for both bots -- a
shared name alone is not enough. Plumbing (``exceptions.py``, ``utils.py``) stays a flat file,
never a directory, so it cannot fire that signal falsely.
"""
