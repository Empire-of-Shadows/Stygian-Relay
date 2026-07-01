"""
Shared database/value-normalization helpers used across extensions.
"""
from datetime import datetime, timezone
from typing import Any, Optional


def normalize_channel_id(value: Any) -> Optional[int]:
    """
    Coerce a channel/role/guild ID into an int.

    Handles the formats MongoDB/BSON may surface:
    - int (already correct)
    - str ("123")
    - {"$numberLong": "123"} (BSON extended JSON)
    - None (returned as None)
    """
    if value is None:
        return None
    if isinstance(value, dict) and "$numberLong" in value:
        return int(value["$numberLong"])
    if isinstance(value, bool):  # avoid accidental True/False -> 1/0
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Return a tz-aware UTC datetime. Naive datetimes are assumed to be UTC
    (Mongo strips tzinfo on read, but stores in UTC).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
