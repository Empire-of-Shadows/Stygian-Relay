"""Stygian-Relay admin seam (bot-owned).

The admin panel installs as the ``admin_engine`` package. This ``admin/`` package holds only
relay's wiring: ``bindings`` (the backend seam the engine reads by name) and ``panel_configs``
(the ``MAIN_PANEL`` tree). ``admin_setup`` is the cog loader shim that injects both into the
engine's ``AdminCog`` at startup.
"""
