# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Generic keyword/content-filter engine (compile + scan; policy stays with the bot).

Promoted from TheDecree's quote NSFW filter. A filter list is a JSON-ish list of entry
dicts; this module owns the matching MECHANICS only - what to do with a hit (reject,
flag NSFW, warn) is per-bot policy applied by the caller.

Entry shape::

    {
      "id": "slur-x",                 # free-form identifier (used in logs)
      "match": "word|other*phrase",   # '|' alternation; '*' wildcard; spaces match any whitespace
      "exceptions": ["classic*"],     # tokens that FULLY match the hit are ignored
      ...any policy fields (tags, severity, ...) the caller reads off the entry...
    }

Matching semantics:
  - Case-insensitive, with word-like boundaries that don't break hyphenated or spaced
    terms (``(?<!\\w)...(?!\\w)``).
  - ``*`` becomes ``.*``; literal regex metacharacters are escaped; runs of spaces match
    any whitespace (``\\s+``).
  - An exception pattern must fully match the matched token to suppress the hit.

Usage::

    compiled = compile_filters(entries)          # once, at load time
    for hit in scan(text, compiled):             # per input
        apply_policy(hit.entry, hit.token)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

# A compiled filter: (match pattern, the original entry, compiled exception patterns).
CompiledEntry = Tuple[re.Pattern, Dict[str, Any], List[re.Pattern]]

# A pattern that can never match (used for empty/invalid "match" values).
_NEVER = re.compile(r"(?!x)x")


@dataclass(frozen=True)
class FilterHit:
    """One confirmed (non-excepted) filter match."""

    entry: Dict[str, Any]
    token: str


def wildcard_to_regex(s: str) -> str:
    r"""Convert a filter token with optional '*' wildcards to a safe regex fragment:
    escape all regex chars, turn '*' into '.*', and collapse spaces to '\s+'."""
    esc = re.escape(s)
    esc = esc.replace(r"\*", ".*")
    esc = re.sub(r"\\\s+", r"\\s+", esc)
    esc = esc.replace(r"\ ", r"\s+")
    return esc


def compile_entry(entry: Dict[str, Any]) -> Tuple[re.Pattern, List[re.Pattern]]:
    """Build the compiled match pattern ('|' alternation + '*' wildcards, word-like
    boundaries) and the compiled exception patterns (which must FULLY match the
    matched token to count) for one entry."""
    raw = entry.get("match", "")
    alts = [a.strip() for a in raw.split("|") if a.strip()]
    if not alts:
        return _NEVER, []

    alt_regexes = [f"(?<!\\w){wildcard_to_regex(a)}(?!\\w)" for a in alts]
    combined_pattern = re.compile("(?:%s)" % "|".join(alt_regexes), re.IGNORECASE)

    exceptions_compiled: List[re.Pattern] = []
    for ex in entry.get("exceptions", []) or []:
        exceptions_compiled.append(re.compile(rf"^(?:{wildcard_to_regex(ex)})$", re.IGNORECASE))

    return combined_pattern, exceptions_compiled


def compile_filters(
    entries: List[Dict[str, Any]],
    *,
    on_error: Optional[Callable[[Dict[str, Any], Exception], None]] = None,
) -> List[CompiledEntry]:
    """Compile a whole filter list. A broken entry is skipped (and reported via
    ``on_error`` or the module logger), never fatal - one bad pattern must not
    disable the rest of the filter."""
    compiled: List[CompiledEntry] = []
    for entry in entries:
        try:
            pattern, exceptions = compile_entry(entry)
            compiled.append((pattern, entry, exceptions))
        except Exception as ce:
            if on_error is not None:
                on_error(entry, ce)
            else:
                logger.exception(f"Failed to compile filter entry {entry.get('id')} - skipping: {ce}")
    return compiled


def scan(text: str, compiled: List[CompiledEntry]) -> Iterator[FilterHit]:
    """Yield every non-excepted hit against ``text`` (searched casefolded).

    At most one hit per entry (the first match), mirroring moderation-filter
    semantics: an entry either fires for an input or it doesn't.
    """
    haystack = (text or "").lower()
    for pattern, entry, ex_list in compiled:
        m = pattern.search(haystack)
        if not m:
            continue
        token = haystack[m.start():m.end()]
        if any(ex.fullmatch(token) for ex in ex_list):
            logger.debug(f"Filter entry '{entry.get('id')}' matched '{token}' but was excepted.")
            continue
        yield FilterHit(entry=entry, token=token)
