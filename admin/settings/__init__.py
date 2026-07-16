"""Stygian-Relay's admin panel seam (bot-owned, NEVER vendored).

The vendored engine beside this package reaches every relay-specific backend through the
names defined here: ``bindings`` (config/audit/premium/cache/panel-role + the static branding
text) and ``panel_configs`` (the MAIN_PANEL tree). Engine files import them as
``from .settings.bindings import ...`` / ``from .settings.panel_configs import MAIN_PANEL``.
"""
