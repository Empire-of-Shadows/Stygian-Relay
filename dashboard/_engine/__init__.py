# VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
# Edit the master at EmpireSystems/dashboard_engine/ and run:
#     python EmpireSystems/tools/sync_dashboard_engine.py
# Drift is enforced by:
#     python EmpireSystems/tools/sync_dashboard_engine.py --check
"""Vendored dashboard backend engine (shared auth: signing, session, CSRF, OAuth, rate limit).

Lands at ``<bot>/dashboard/_engine/`` in each bot. Everything here is engine-owned and
vendored byte-for-byte from ``EmpireSystems/dashboard_engine/backend/``; the bot's own
``config.py`` / ``db.py`` / ``app.py`` / routers / ``auth/panel_role.py`` /
``auth/dependencies.py`` are the seam. The engine only depends on the seam through
``dashboard.config`` and the ``dashboard.db.shared_sessions()`` / ``dashboard.db.oauth_states()``
accessors.
"""
