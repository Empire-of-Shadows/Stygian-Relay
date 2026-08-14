"""Per-member privacy choices for Stygian-Relay (bot-owned seam, NOT vendored).

Relay is the one bot in the fleet that republishes a member's own words somewhere else,
so a member gets two switches over that, and this module is the bot side of them:

  ``relay_messages``  Do not relay my messages. Nothing I post in a watched channel is
                      copied anywhere, by any rule, in any server.
  ``show_name``       Do not show my name on forwarded copies. The message is still
                      relayed, but the author line is left off it.
  ``all``             Both of the above (the engine's ``global_key``).

POLARITY, because it reads backwards at a glance: a flag set to ``True`` means the member
has OPTED OUT of that thing. ``show_name: True`` means "do not show my name". That is the
shared ``UserPreferenceCache`` convention (``is_opted_out(user_id, key)`` is true when the
flag is set), and matching it is what lets ``all`` gate both without special-casing.

Owner ruling 2026-08-13: member privacy wins over mirror completeness. A destination
channel showing an incomplete copy of a conversation is the accepted cost.

IDS ARE STRINGS. Every id in ``discord_forwarding_bot`` is stored as a string, and the
engine cache uses the id exactly as it is given for the Mongo lookup (only the in-memory
cache key is ``str()``-ed). discord.py hands out ``int`` ids, so every caller on the bot
side MUST pass ``str(user.id)`` - an int would query ``{"user_id": 123}`` against a
document holding ``"123"``, match nothing, and silently forward a member who opted out.
``opted_out_of()`` below coerces for its callers so the hot path cannot get that wrong.

The dashboard writes the same documents through ``dashboard/services/user_data.py``; it
is standalone and does not import this package, so the document shape is stated in both
places and must move together.
"""

from __future__ import annotations

from typing import Optional

from ..services.user_preference_cache import UserPreferenceCache
from .collections import USER_PREFERENCES, db_manager

#: Document sub-dict holding the flag map. Mirrors the dashboard's writer.
FLAGS_FIELD = "features"

#: "Do not relay my messages at all."
FLAG_RELAY_MESSAGES = "relay_messages"

#: "Relay my messages, but do not put my name on them."
FLAG_SHOW_NAME = "show_name"

#: The master switch, checked by the engine on every ``is_opted_out`` call.
FLAG_ALL = "all"

#: Every flag the bot and the dashboard agree on, in the order the page shows them.
PREFERENCE_FLAGS: tuple[str, ...] = (FLAG_ALL, FLAG_RELAY_MESSAGES, FLAG_SHOW_NAME)

# How long a member's choices may be stale on the forwarding path. Sixty seconds is the
# engine default and is what the dashboard promises the member ("within about a minute").
_CACHE_TTL_SECONDS = 60

_cache: Optional[UserPreferenceCache] = None


def preference_cache() -> UserPreferenceCache:
    """The shared per-user preference cache, built on first use.

    Built lazily rather than at import: ``get_collection_manager`` raises until
    ``db_manager.initialize()`` has run, and this module is imported by a cog whose
    import can precede that.
    """
    global _cache
    if _cache is None:
        _cache = UserPreferenceCache(
            db_manager.get_collection_manager(USER_PREFERENCES),
            id_field="user_id",
            flags_field=FLAGS_FIELD,
            # Fixed key set (not dynamic): relay's flags are per-feature, not per-guild.
            keys=(FLAG_RELAY_MESSAGES, FLAG_SHOW_NAME),
            global_key=FLAG_ALL,
            ttl=_CACHE_TTL_SECONDS,
        )
    return _cache


async def opted_out_of(user_id, flag: str) -> bool:
    """True when this member has opted out of ``flag`` (or out of everything).

    FAIL-OPEN. If the preference store cannot be read the member is treated as not
    opted out, so a Mongo blip degrades relay to its previous behaviour rather than
    silently stopping every forward in the fleet. The engine's own loader already
    swallows query errors the same way; this catches the construction path too (the
    manager not being attached yet).

    Accepts an ``int`` or a ``str`` and coerces to ``str``: discord.py ids are ints and
    the stored ids are strings.
    """
    try:
        return await preference_cache().is_opted_out(str(user_id), flag)
    except Exception:
        return False


def invalidate(user_id) -> None:
    """Drop one member's cached choices (after a write, if one ever happens bot-side)."""
    try:
        preference_cache().invalidate(str(user_id))
    except Exception:
        return
