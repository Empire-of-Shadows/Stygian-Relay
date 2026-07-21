# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Color helpers - convert between ``#RRGGBB`` strings and stored ints.

Reused by any branding/color feature (Decree embed color, Codex color sets).
``hex_validator`` plugs into a modal leaf (see ``config.leaves.color_leaf``).
"""

from __future__ import annotations

from typing import Optional


def parse_hex(raw: str) -> Optional[int]:
    """Parse ``#RRGGBB`` / ``RRGGBB`` (and 3-digit shorthand) into an int, or None."""
    if raw is None:
        return None
    s = str(raw).strip().lstrip("#")
    if len(s) == 3 and all(c in "0123456789abcdefABCDEF" for c in s):
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        return int(s, 16)
    except ValueError:
        return None


def to_hex(value: int) -> str:
    """Format a stored int color as ``#RRGGBB``."""
    return f"#{int(value) & 0xFFFFFF:06X}"


def hex_validator(raw: str):
    """Modal validator: returns ``(ok, int_value, error_message)``."""
    value = parse_hex(raw)
    if value is None:
        return False, None, "Enter a hex color like #5865F2."
    return True, value, ""
