"""Stygian-Relay's storage seam (bot-owned, NEVER vendored).

The only storage code relay writes by hand: ``bindings`` (URIs, cache choice, watched
collections) and ``collections`` (the consolidated collection registry AND the concrete
DatabaseManager + shared ``db_manager`` singleton the rest of the bot imports). This replaced
the old ``define_collections`` + ``database_properties`` + ``manager`` trio.
"""
