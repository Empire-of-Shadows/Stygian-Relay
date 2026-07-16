# ───────────────────────────────────────────────────────────────────────────
# VENDORED from admin_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Collection actions: document doers + paginated-list node + export."""

from .documents import (
    list_documents,
    count_documents,
    delete_document,
    purge_collection,
    upsert_document,
    insert_document,
)
from .nodes import paginated_list_node
from .export import export_documents, export_action
from .scoped import mutate_scoped

__all__ = [
    "list_documents", "count_documents", "delete_document", "purge_collection",
    "upsert_document", "insert_document",
    "paginated_list_node",
    "export_documents", "export_action",
    "mutate_scoped",
]
