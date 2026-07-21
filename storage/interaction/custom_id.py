# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""``feature:action:target`` custom-id codec.

Standardizes the prefix-routing convention already used ad-hoc across the bots (TheCodex
guide ``g:nav:<page>`` / ``g:back``, ``wyr:option1``). ``pack`` builds a custom id;
``parse`` splits one back into its parts. Discord caps a ``custom_id`` at 100 chars - keep
``target`` short (an id, not a payload); store anything larger in ``InteractionStateStore``.
"""

from __future__ import annotations

from typing import NamedTuple

_SEP = ":"
_MAX_LEN = 100  # Discord's hard limit on component custom_id length


class CustomId(NamedTuple):
    """A parsed custom id. ``action`` / ``target`` are ``""`` when absent."""

    feature: str
    action: str
    target: str


def pack(feature: str, action: str = "", target: str = "") -> str:
    """Build a ``feature[:action[:target]]`` custom id, trimming trailing empties.

    Raises ``ValueError`` if the result would exceed Discord's 100-char limit or if
    ``feature`` is empty."""
    if not feature:
        raise ValueError("custom_id requires a non-empty feature")
    parts = [feature, action, target]
    while len(parts) > 1 and parts[-1] == "":
        parts.pop()
    cid = _SEP.join(parts)
    if len(cid) > _MAX_LEN:
        raise ValueError(f"custom_id {cid!r} exceeds Discord's {_MAX_LEN}-char limit")
    return cid


def parse(custom_id: str) -> CustomId:
    """Split a custom id into ``(feature, action, target)``. ``target`` keeps any further
    ``:`` separators (only the first two are split on), so values may contain colons."""
    feature, _, rest = custom_id.partition(_SEP)
    action, _, target = rest.partition(_SEP)
    return CustomId(feature=feature, action=action, target=target)
