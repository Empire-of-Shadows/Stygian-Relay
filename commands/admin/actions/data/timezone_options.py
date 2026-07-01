# ───────────────────────────────────────────────────────────────────────────
# VENDORED from admin_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Timezone option helpers for the admin panel's grouped timezone picker.

Pure, guild-independent functions that generate the region → zone tree from
``pytz.common_timezones`` (the curated IANA list — better UX than the full
``all_timezones``). Consumed by a ``grouped_select_leaf`` (timezone) and rendered
by the generic engine. No state, no DB — the tz database is static, so the buckets
are built once at import.
"""

from __future__ import annotations

from datetime import datetime

import pytz

# IANA prefix → display label, in presentation order. Zones whose first path
# segment isn't a key here (single-word legacy names like "UTC"/"GMT") bucket
# under "Etc".
REGION_LABELS: dict[str, str] = {
    "America": "Americas",
    "Europe": "Europe",
    "Asia": "Asia",
    "Africa": "Africa",
    "Australia": "Australia",
    "Pacific": "Pacific",
    "Indian": "Indian Ocean",
    "Atlantic": "Atlantic",
    "Antarctica": "Antarctica",
    "Arctic": "Arctic",
    "Etc": "UTC / Etc",
}


def _region_of(tz: str) -> str:
    prefix = tz.split("/", 1)[0]
    return prefix if prefix in REGION_LABELS else "Etc"


# Bucket every common zone once at import (the tz database is static).
_ZONES_BY_REGION: dict[str, list[str]] = {}
for _tz in pytz.common_timezones:
    _ZONES_BY_REGION.setdefault(_region_of(_tz), []).append(_tz)
for _zones in _ZONES_BY_REGION.values():
    _zones.sort()


def get_regions() -> list[tuple[str, str]]:
    """Return ``(region_prefix, label)`` for every region that has zones,
    ordered by ``REGION_LABELS`` insertion order."""
    return [
        (prefix, label)
        for prefix, label in REGION_LABELS.items()
        if _ZONES_BY_REGION.get(prefix)
    ]


def get_zones(region_prefix: str) -> list[str]:
    """Return the sorted IANA zone names within ``region_prefix``."""
    return list(_ZONES_BY_REGION.get(region_prefix, ()))


def region_label(region_prefix: str) -> str:
    return REGION_LABELS.get(region_prefix, region_prefix)


def pretty_zone(tz: str) -> str:
    """Human label for a zone, dropping the region prefix:
    ``America/New_York`` → ``New York``; ``America/Argentina/Salta`` →
    ``Argentina / Salta``; ``UTC`` → ``UTC``."""
    tail = tz.split("/", 1)[-1] if "/" in tz else tz
    return tail.replace("_", " ").replace("/", " / ")


def offset_label(tz: str) -> str:
    """Current UTC offset for ``tz`` as ``UTC+02:00`` / ``UTC−05:00`` (uses a
    proper minus-sign glyph). DST-accurate — evaluated at call time."""
    try:
        off = datetime.now(pytz.timezone(tz)).utcoffset()
    except Exception:
        return "UTC"
    if off is None:
        return "UTC"
    total = int(off.total_seconds())
    sign = "+" if total >= 0 else "−"  # − minus sign
    hours, minutes = divmod(abs(total) // 60, 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"
