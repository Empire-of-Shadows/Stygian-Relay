# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""PremiumManager - entitlement persistence + derived premium state.

Master-owned, bot-agnostic, and discord.py-free: it stores already-normalized entitlement
dicts (the cog converts ``discord.Entitlement`` -> dict and resolves the SKU -> tier before
calling in), so the same logic serves every bot. Reaches Mongo through the shared engine
``db_manager`` (``get_collection`` / ``db_client``), exactly like ``GuildManager``.

Persists two collections in ``discord_forwarding_bot``:

- ``entitlements``   - one raw record per entitlement ``id`` (``_id == entitlement_id``), so
  every write is idempotent: event + reconcile + interaction for the same id converge.
- ``premium_state``  - one derived doc per scope (``_id == "{scope}:{scope_id}"``) that the
  hot read paths (is_premium / limits / dashboard / admin) consume instead of the raw records.

Reconcile health (last run, counts) is a subkey of the ``bot_settings`` global_config doc.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from pymongo import UpdateOne

from ..utils import ensure_utc
from .constants import (
    DISCORD_SOURCES,
    ENTITLEMENTS_COLLECTION,
    PREMIUM_STATE_COLLECTION,
    RECONCILE_HEALTH_KEY,
    SCOPE_GUILD,
    SCOPE_USER,
    SOURCE_MANUAL,
    SOURCE_RECONCILE,
    TIER_UNKNOWN,
)
from .state import PremiumState, compute_state

logger = logging.getLogger("PremiumManager")

_DB = "discord_forwarding_bot"

# Canonical entitlement fields the manager mirrors from Discord (or a manual grant). Bookkeeping
# fields (first_seen_at / last_updated_at / fulfilled / consumed_at) are owned by the manager and
# are NOT overwritten from an incoming payload here.
_MIRRORED_FIELDS = (
    "sku_id",
    "application_id",
    "type",
    "deleted",
    "starts_at",
    "ends_at",
    "consumed",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_id(scope: str, scope_id: str) -> str:
    return f"{scope}:{scope_id}"


class PremiumManager:
    """Owns the entitlements + premium_state collections and the reconcile safety net."""

    def __init__(
        self,
        database_core,
        *,
        on_state_change: Optional[Callable[[str, str], Any]] = None,
        tier_priority: Optional[List[str]] = None,
    ):
        self.db = database_core
        # Fired after a scope's premium_state is recomputed, so e.g. GuildManager can drop its
        # premium cache. May be sync or async; both are handled.
        self.on_state_change = on_state_change
        # Highest-tier-first ordering for PremiumState.tier. The cog sets it from its SKU map.
        self.tier_priority = tier_priority or []

    # ── collection handles ────────────────────────────────────────────────────────

    def _entitlements(self):
        return self.db.get_collection(_DB, ENTITLEMENTS_COLLECTION)

    def _states(self):
        return self.db.get_collection(_DB, PREMIUM_STATE_COLLECTION)

    def _bot_settings(self):
        return self.db.get_collection(_DB, "bot_settings")

    # ── lifecycle ─────────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Ensure indexes and run the one-shot legacy-subscription migration. Idempotent."""
        await self._ensure_indexes()
        try:
            migrated = await self.migrate_legacy_subscriptions()
            if migrated:
                logger.info(f"Migrated {migrated} legacy premium subscription(s) into entitlements")
        except Exception as e:
            logger.warning(f"Legacy premium-subscription migration failed (non-fatal): {e}", exc_info=True)

    async def _ensure_indexes(self) -> None:
        try:
            db = self.db.db_client[_DB]
            ent = db[ENTITLEMENTS_COLLECTION]
            # _id == entitlement_id already gives uniqueness; these back the read paths.
            await ent.create_index([("scope", 1), ("scope_id", 1), ("deleted", 1)])
            await ent.create_index("scope_id")
            await ent.create_index("sku_id")
            await ent.create_index("guild_id")
            await ent.create_index("user_id")
            await ent.create_index("source")

            state = db[PREMIUM_STATE_COLLECTION]
            await state.create_index([("scope", 1), ("is_premium", 1)])
            await state.create_index("scope_id")
            logger.info("✅ Premium indexes verified")
        except Exception as e:
            logger.warning(f"Failed to ensure premium indexes (non-fatal): {e}")

    # ── normalization ─────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_scope(entitlement: Dict[str, Any]) -> tuple[str, str]:
        """Derive (scope, scope_id) from an incoming record.

        Explicit scope/scope_id win; otherwise guild_id -> guild, else user_id -> user.
        """
        scope = entitlement.get("scope")
        scope_id = entitlement.get("scope_id")
        if scope and scope_id:
            return scope, str(scope_id)
        gid = entitlement.get("guild_id")
        if gid:
            return SCOPE_GUILD, str(gid)
        uid = entitlement.get("user_id")
        if uid:
            return SCOPE_USER, str(uid)
        raise ValueError("entitlement has neither scope/scope_id nor guild_id/user_id")

    def _build_set(
        self,
        entitlement: Dict[str, Any],
        *,
        source: Optional[str],
        tier: Optional[str],
        now: datetime,
    ) -> Dict[str, Any]:
        scope, scope_id = self._resolve_scope(entitlement)
        set_fields: Dict[str, Any] = {
            "entitlement_id": str(entitlement["entitlement_id"]),
            "scope": scope,
            "scope_id": scope_id,
            "guild_id": str(entitlement["guild_id"]) if entitlement.get("guild_id") else (
                scope_id if scope == SCOPE_GUILD else None
            ),
            "user_id": str(entitlement["user_id"]) if entitlement.get("user_id") else (
                scope_id if scope == SCOPE_USER else None
            ),
            "tier": tier if tier is not None else (entitlement.get("tier") or TIER_UNKNOWN),
            "source": source if source is not None else entitlement.get("source"),
            "last_updated_at": now,
        }
        for key in _MIRRORED_FIELDS:
            if key in entitlement:
                value = entitlement[key]
                if key in ("starts_at", "ends_at"):
                    value = ensure_utc(value)
                set_fields[key] = value
        # Carry provenance / actor fields when present (manual grants, legacy migration).
        for extra in ("granted_by", "legacy_sub_id"):
            if entitlement.get(extra) is not None:
                set_fields[extra] = entitlement[extra]
        set_fields.setdefault("deleted", bool(entitlement.get("deleted", False)))
        set_fields.setdefault("consumed", bool(entitlement.get("consumed", False)))
        return set_fields

    # ── writes ────────────────────────────────────────────────────────────────────

    async def record_entitlement(
        self,
        entitlement: Dict[str, Any],
        *,
        source: Optional[str] = None,
        tier: Optional[str] = None,
        recompute: bool = True,
    ) -> Dict[str, Any]:
        """Idempotently upsert one entitlement (keyed by its id) and recompute the scope.

        ``entitlement`` must carry ``entitlement_id`` and enough to resolve a scope (either
        ``scope``+``scope_id`` or ``guild_id``/``user_id``). ``source``/``tier`` override the
        payload's own values. Returns the stored record.
        """
        now = _now()
        set_fields = self._build_set(entitlement, source=source, tier=tier, now=now)
        eid = set_fields["entitlement_id"]
        await self._entitlements().update_one(
            {"_id": eid},
            {"$set": set_fields, "$setOnInsert": {"first_seen_at": now}},
            upsert=True,
        )
        stored = await self._entitlements().find_one({"_id": eid})
        if recompute:
            await self.recompute_state(set_fields["scope"], set_fields["scope_id"])
        return stored

    async def mark_deleted(self, entitlement_id: str) -> bool:
        """Mark a single entitlement deleted (refund/removal) and recompute its scope."""
        now = _now()
        doc = await self._entitlements().find_one_and_update(
            {"_id": str(entitlement_id)},
            {"$set": {"deleted": True, "last_updated_at": now}},
        )
        if not doc:
            return False
        await self.recompute_state(doc["scope"], doc["scope_id"])
        return True

    async def mark_fulfilled(self, entitlement_id: str, *, consumed: bool = False) -> bool:
        """Record that a one-time SKU was fulfilled (and optionally consumed). Idempotent."""
        now = _now()
        updates: Dict[str, Any] = {"fulfilled": True, "last_updated_at": now}
        if consumed:
            updates["consumed"] = True
            updates["consumed_at"] = now
        doc = await self._entitlements().find_one_and_update(
            {"_id": str(entitlement_id)},
            {"$set": updates},
        )
        if not doc:
            return False
        if consumed:
            await self.recompute_state(doc["scope"], doc["scope_id"])
        return True

    async def grant_manual(
        self,
        scope: str,
        scope_id: str,
        tier: str,
        *,
        duration_days: Optional[int] = None,
        sku_id: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Owner-granted premium that is not a real Discord entitlement.

        Bridges the gap until Discord monetization/SKUs are live (and covers comped grants).
        ``duration_days=None`` grants indefinitely (a lifetime-style grant).
        """
        now = _now()
        ends_at = now + timedelta(days=int(duration_days)) if duration_days else None
        record = {
            "entitlement_id": f"manual:{uuid.uuid4().hex}",
            "sku_id": sku_id or f"manual-{tier}",
            "application_id": None,
            "scope": scope,
            "scope_id": str(scope_id),
            "type": "manual",
            "tier": tier,
            "deleted": False,
            "starts_at": now,
            "ends_at": ends_at,
            "consumed": False,
            "source": SOURCE_MANUAL,
            "granted_by": str(actor_id) if actor_id else None,
        }
        return await self.record_entitlement(record, source=SOURCE_MANUAL, tier=tier)

    async def revoke_manual(self, scope: str, scope_id: str) -> int:
        """Delete a scope's manual grants (real Discord entitlements are left untouched)."""
        now = _now()
        res = await self._entitlements().update_many(
            {"scope": scope, "scope_id": str(scope_id), "source": SOURCE_MANUAL, "deleted": False},
            {"$set": {"deleted": True, "last_updated_at": now}},
        )
        await self.recompute_state(scope, str(scope_id))
        return int(res.modified_count)

    # ── reconciliation (the missed-event safety net) ──────────────────────────────

    async def reconcile(
        self,
        records: List[Dict[str, Any]],
        *,
        sku_ids: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """Upsert everything a List-Entitlements pass returned, then mark-and-sweep the rest.

        ``records`` are normalized dicts (tier already resolved) from a SUCCESSFUL fetch. Any
        stored, non-deleted, Discord-sourced entitlement that is NOT in the fetched set is
        marked deleted so a missed ENTITLEMENT_DELETE still gets caught. ``sku_ids`` bounds the
        sweep to the SKUs actually queried. Manual grants are never swept.

        Guard: if the fetch returned nothing AND no sku bound is given, the sweep is skipped -
        a wipe on an empty/unbounded result is never correct (a failed fetch must not lapse
        everyone). Callers pass results only on success and never wipe on error.
        """
        now = _now()
        seen_ids: set[str] = set()
        affected: set[tuple[str, str]] = set()
        ops: List[UpdateOne] = []

        for r in records:
            set_fields = self._build_set(r, source=SOURCE_RECONCILE, tier=r.get("tier"), now=now)
            eid = set_fields["entitlement_id"]
            seen_ids.add(eid)
            affected.add((set_fields["scope"], set_fields["scope_id"]))
            ops.append(UpdateOne(
                {"_id": eid},
                {"$set": set_fields, "$setOnInsert": {"first_seen_at": now}},
                upsert=True,
            ))

        added = updated = 0
        if ops:
            result = await self._entitlements().bulk_write(ops, ordered=False)
            added = int(result.upserted_count)
            updated = int(result.modified_count)

        expired = 0
        if seen_ids or sku_ids:
            sweep_filter: Dict[str, Any] = {
                "deleted": False,
                "source": {"$in": list(DISCORD_SOURCES)},
                "_id": {"$nin": list(seen_ids)},
            }
            if sku_ids:
                sweep_filter["sku_id"] = {"$in": list(sku_ids)}
            # Note the scopes that are about to lose an entitlement so we recompute them too.
            async for d in self._entitlements().find(sweep_filter, {"scope": 1, "scope_id": 1}):
                affected.add((d.get("scope"), d.get("scope_id")))
            sweep = await self._entitlements().update_many(
                sweep_filter,
                {"$set": {"deleted": True, "last_updated_at": now, "swept_at": now}},
            )
            expired = int(sweep.modified_count)
        else:
            logger.warning(
                "Reconcile got an empty, unbounded result set - skipping mark-and-sweep to "
                "avoid wiping premium on a possibly-failed fetch."
            )

        for scope, scope_id in affected:
            if scope and scope_id:
                await self.recompute_state(scope, scope_id)

        summary = {"added": added, "updated": updated, "expired": expired, "seen": len(seen_ids)}
        await self._write_reconcile_health("ok", summary=summary)
        logger.info(
            f"Premium reconcile: +{added} new, {updated} updated, {expired} expired, "
            f"{len(seen_ids)} active"
        )
        return summary

    async def record_reconcile_error(self, message: str) -> None:
        """Note a failed reconcile in the health record without touching stored entitlements."""
        await self._write_reconcile_health("error", error=str(message)[:500])

    async def _write_reconcile_health(
        self, status: str, *, summary: Optional[Dict[str, int]] = None, error: Optional[str] = None
    ) -> None:
        payload: Dict[str, Any] = {"last_run_at": _now(), "last_status": status}
        if summary:
            payload.update(summary)
        if error:
            payload["error"] = error
        try:
            await self._bot_settings().update_one(
                {"_id": "global_config"},
                {"$set": {RECONCILE_HEALTH_KEY: payload}},
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"Failed to write reconcile health (non-fatal): {e}")

    async def get_reconcile_health(self) -> Optional[Dict[str, Any]]:
        doc = await self._bot_settings().find_one({"_id": "global_config"}, {RECONCILE_HEALTH_KEY: 1})
        return (doc or {}).get(RECONCILE_HEALTH_KEY)

    # ── derived state ─────────────────────────────────────────────────────────────

    async def recompute_state(self, scope: str, scope_id: str) -> PremiumState:
        """Recompute and persist the derived premium_state doc for one scope."""
        scope_id = str(scope_id)
        records = [
            d async for d in self._entitlements().find({"scope": scope, "scope_id": scope_id})
        ]
        state = compute_state(scope, scope_id, records, tier_priority=self.tier_priority)
        await self._states().update_one(
            {"_id": _state_id(scope, scope_id)},
            {"$set": state.to_doc()},
            upsert=True,
        )
        await self._fire_state_change(scope, scope_id)
        return state

    async def _fire_state_change(self, scope: str, scope_id: str) -> None:
        if not self.on_state_change:
            return
        try:
            result = self.on_state_change(scope, scope_id)
            if hasattr(result, "__await__"):
                await result
        except Exception as e:
            logger.debug(f"on_state_change hook failed for {scope}:{scope_id}: {e}")

    async def get_state(self, scope: str, scope_id: str) -> PremiumState:
        """Read the stored premium_state for a scope (free-tier default when absent)."""
        doc = await self._states().find_one({"_id": _state_id(scope, str(scope_id))})
        if not doc:
            return PremiumState(scope=scope, scope_id=str(scope_id))
        return PremiumState.from_doc(doc)

    async def is_premium(self, scope: str, scope_id: str) -> bool:
        """True if the scope is premium right now.

        Reads the derived doc but re-checks expiry so a time-limited grant that lapsed since
        the last recompute reports correctly (and is lazily recomputed) without waiting for
        the next reconcile pass.
        """
        state = await self.get_state(scope, str(scope_id))
        if not state.is_premium:
            return False
        if state.expires_at is not None and state.expires_at <= _now():
            # Lapsed since last recompute - refresh the doc, then report the fresh answer.
            fresh = await self.recompute_state(scope, str(scope_id))
            return fresh.is_premium
        return True

    async def get_tier(self, scope: str, scope_id: str) -> Optional[str]:
        state = await self.get_state(scope, str(scope_id))
        return state.tier if state.is_premium else None

    # Guild convenience wrappers (per-user callers pass SCOPE_USER explicitly).
    async def is_premium_guild(self, guild_id: str) -> bool:
        return await self.is_premium(SCOPE_GUILD, str(guild_id))

    async def get_guild_state(self, guild_id: str) -> PremiumState:
        return await self.get_state(SCOPE_GUILD, str(guild_id))

    # ── reads for admin / dashboard ───────────────────────────────────────────────

    async def list_entitlements(
        self,
        *,
        scope: Optional[str] = None,
        scope_id: Optional[str] = None,
        include_deleted: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if scope:
            query["scope"] = scope
        if scope_id:
            query["scope_id"] = str(scope_id)
        if not include_deleted:
            query["deleted"] = False
        cursor = self._entitlements().find(query).sort("last_updated_at", -1)
        return await cursor.to_list(length=limit)

    async def list_premium_states(
        self, *, scope: str = SCOPE_GUILD, only_premium: bool = True, limit: int = 500
    ) -> List[PremiumState]:
        query: Dict[str, Any] = {"scope": scope}
        if only_premium:
            query["is_premium"] = True
        cursor = self._states().find(query).limit(limit)
        return [PremiumState.from_doc(d) async for d in cursor]

    # ── one-shot migration ────────────────────────────────────────────────────────

    async def migrate_legacy_subscriptions(self, *, default_tier: str = "premium") -> int:
        """Convert still-active legacy premium_subscriptions into manual entitlements.

        Retiring the code-redemption system must not drop premium a guild already paid for.
        Deterministic id (``legacy:<sub _id>``) makes this idempotent; the source
        premium_subscriptions docs are preserved, not deleted.
        """
        now = _now()
        subs = self.db.get_collection(_DB, "premium_subscriptions")
        ent = self._entitlements()
        migrated = 0
        async for sub in subs.find({"is_active": True}):
            is_lifetime = bool(sub.get("is_lifetime"))
            expires_at = ensure_utc(sub.get("expires_at"))
            if not is_lifetime and (expires_at is None or expires_at <= now):
                continue  # already lapsed - nothing to carry over
            gid = sub.get("guild_id")
            if not gid:
                continue
            gid = str(gid)
            eid = f"legacy:{sub.get('_id')}"
            set_fields = {
                "entitlement_id": eid,
                "sku_id": "legacy-migration",
                "application_id": None,
                "scope": SCOPE_GUILD,
                "scope_id": gid,
                "guild_id": gid,
                "user_id": None,
                "type": "manual",
                "tier": default_tier,
                "deleted": False,
                "starts_at": ensure_utc(sub.get("activated_at")) or now,
                "ends_at": None if is_lifetime else expires_at,
                "consumed": False,
                "source": SOURCE_MANUAL,
                "legacy_sub_id": str(sub.get("_id")),
                "last_updated_at": now,
            }
            result = await ent.update_one(
                {"_id": eid},
                {"$set": set_fields, "$setOnInsert": {"first_seen_at": now}},
                upsert=True,
            )
            if result.upserted_id is not None:
                migrated += 1
            await self.recompute_state(SCOPE_GUILD, gid)
        return migrated
