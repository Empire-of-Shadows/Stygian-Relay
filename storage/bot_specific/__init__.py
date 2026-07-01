"""Bot-specific storage code (NOT vendored).

Home for storage logic unique to one bot. Such code still reaches MongoDB only through the
generic engine (the shared ``db_manager`` / ``CollectionManager``), so every bot reads and
writes the same way. See ``relay/`` for Stygian-Relay's domain layer.
"""
