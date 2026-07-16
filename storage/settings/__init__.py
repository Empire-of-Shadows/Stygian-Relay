"""Stygian-Relay's storage seam (bot-owned, NEVER vendored).

The only storage code relay writes by hand: ``bindings`` (URIs, cache choice, watched
collections), ``define_collections`` + ``database_properties`` (the collection registry and
its accessors), and ``manager`` (the concrete DatabaseManager and the shared ``db_manager``
singleton the rest of the bot imports).
"""
