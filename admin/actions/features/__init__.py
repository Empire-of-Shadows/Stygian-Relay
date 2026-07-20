# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Higher-level feature builders assembled from the doers/factories.

Small set for now; grows as cross-bot patterns prove stable.
"""

from .access_lists import access_list_pair
from .panel_roles import panel_roles_pair

__all__ = ["access_list_pair", "panel_roles_pair"]
