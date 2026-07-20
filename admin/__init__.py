# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""
Admin Commands Module - Components v2

Provides the unified /admin panel command for all bot configuration.
Uses Discord Components v2 LayoutViews for interactive UI.
"""

from .admin_cog import AdminCog

__all__ = ["AdminCog"]
