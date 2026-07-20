# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""Reusable dict-editor value validators for numeric maps.

The dict-editor value-validator contract is ``(raw: str) -> (ok, error_msg, parsed)``
(note: distinct from the modal-input validator's ``(ok, value, error)`` order). Pair these
with ``dict_editor_leaf(value_validator=...)`` for ``{key: number}`` maps such as per-channel
multipliers or counts, so the stored value is a real int/float rather than the raw string.
"""

from __future__ import annotations

from typing import Callable, Optional


def int_value_validator(minimum: Optional[int] = None,
                        maximum: Optional[int] = None) -> Callable:
    """Return a dict-editor value validator that parses a whole number (range-checked)."""
    def _v(raw: str):
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            return False, "Enter a whole number.", None
        if minimum is not None and n < minimum:
            return False, f"Must be at least {minimum}.", None
        if maximum is not None and n > maximum:
            return False, f"Must be at most {maximum}.", None
        return True, "", n
    return _v


def float_value_validator(minimum: Optional[float] = None,
                          maximum: Optional[float] = None) -> Callable:
    """Return a dict-editor value validator that parses a float (range-checked)."""
    def _v(raw: str):
        try:
            n = float(str(raw).strip())
        except (TypeError, ValueError):
            return False, "Enter a number (decimals allowed).", None
        if minimum is not None and n < minimum:
            return False, f"Must be at least {minimum}.", None
        if maximum is not None and n > maximum:
            return False, f"Must be at most {maximum}.", None
        return True, "", n
    return _v
