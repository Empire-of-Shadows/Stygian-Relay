# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
class DatabaseConnectionError(Exception):
    """
    Raised when there is an issue with the database connection.
    This could be due to a network error, authentication failure, or other connection-related issues.
    """
    pass


class DatabaseOperationError(Exception):
    """
    Raised when a database operation fails.
    This could be due to a query error, constraint violation, or other operation-related issues.
    """
    pass