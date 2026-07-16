"""Stygian-Relay storage seam (bot-owned).

The storage engine installs as the ``storage_engine`` package. This ``storage/`` package holds
only relay's wiring: ``bindings`` (Mongo URIs + cache), ``define_collections`` (the collection
registry; typed ``db_manager.<key>`` accessors are auto-derived by the engine), the concrete
``manager`` (``db_manager``), and the ``bot_specific/relay/`` domain layer. Import the engine absolutely
(``from storage_engine... import ...``); these siblings import each other via ``storage.*``.
"""
