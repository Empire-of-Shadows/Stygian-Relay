# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Tiny text-normalization helpers shared across bots."""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    """Normalize free text for duplicate detection: trim, casefold, and collapse
    internal whitespace to single spaces ("Hello   World" == "hello world")."""
    return _WS.sub(" ", (s or "").strip()).casefold()
