# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
import copy
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Dict, Any, List, Optional, Union

import backoff
from pymongo.asynchronous.collection import AsyncCollection
from pymongo import UpdateOne, InsertOne, DeleteOne, ReplaceOne
from pymongo.errors import BulkWriteError, ConnectionFailure, OperationFailure

from .collection_config import CollectionConfig
from ..cache.backend import CacheBackend
from ..cache.local import LocalCache
from ..logging_compat import get_logger

logger = get_logger("CollectionManager")


def _is_retryable(exc: Exception) -> bool:
    """Only genuinely transient failures should be retried.

    ConnectionFailure (network / server unavailable) is always retryable. An
    OperationFailure is retried ONLY when the server tagged it with a retryable
    label -- deterministic failures like DuplicateKeyError, authentication errors
    and malformed queries would otherwise be re-sent 2-3x (an ack-lost insert retry
    re-sends the same _id and surfaces a spurious DuplicateKeyError; an $inc retry on
    top of driver-level retryWrites risks a double-apply).
    """
    if isinstance(exc, ConnectionFailure):
        return True
    if isinstance(exc, OperationFailure):
        return exc.has_error_label("RetryableWriteError") or exc.has_error_label(
            "TransientTransactionError"
        )
    return False


def with_retry(max_retries: int = 3, backoff_factor: float = 1.0):
    """Decorator for database operations with exponential backoff retry.

    Retries only transient failures (see ``_is_retryable``); deterministic errors
    surface immediately on the first attempt.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            @backoff.on_exception(
                backoff.expo,
                (ConnectionFailure, OperationFailure),
                max_tries=max_retries,
                factor=backoff_factor,
                jitter=backoff.random_jitter,
                giveup=lambda e: not _is_retryable(e),
            )
            async def _execute():
                return await func(*args, **kwargs)

            return await _execute()

        return wrapper

    return decorator

class CollectionManager:
    """Manages CRUD operations for a specific collection with caching and optimization.

    Caching is routed through a pluggable ``CacheBackend`` (hit-first on reads,
    invalidated on writes). If no backend is supplied a private ``LocalCache`` is created
    so the manager works standalone; in a DatabaseManager all managers SHARE one backend
    so the change-stream watcher can invalidate across collections. Cache keys are
    namespaced ``"<collection>:<cache_key>"`` so invalidation is collection-scoped.
    """

    def __init__(self, collection: AsyncCollection, config: CollectionConfig,
                 cache: Optional[CacheBackend] = None,
                 default_cache_duration: int = 300):
        self.collection = collection
        self.config = config
        self.name = config.name
        self._default_cache_duration = default_cache_duration
        self._cache: CacheBackend = cache or LocalCache(default_ttl=default_cache_duration)

    def _ckey(self, cache_key: str) -> str:
        """Namespace a caller-supplied cache key under this collection."""
        return f"{self.name}:{cache_key}"

    def _stamp_update(self, update_dict):
        """Return an update with ``updated_at`` stamped, WITHOUT mutating the caller's
        dict. Aggregation-pipeline updates (a list) are passed through untouched -- they
        take no ``$set`` (the old code raised TypeError on them)."""
        if isinstance(update_dict, list):
            return update_dict
        stamped = dict(update_dict)
        stamped['$set'] = {**stamped.get('$set', {}), 'updated_at': datetime.now(tz=timezone.utc)}
        return stamped

    def _invalidate_cache(self, pattern: str = None) -> None:
        """Invalidate this collection's cached entries (optionally a sub-pattern)."""
        scope = self._ckey(pattern) if pattern else f"{self.name}:"
        self._cache.invalidate(scope)

    # CREATE Operations

    @with_retry(max_retries=3)
    async def create_one(self, document: Dict[str, Any], **kwargs) -> Any:
        """Insert a single document. Returns the inserted document's ID."""
        try:
            document['created_at'] = datetime.now(tz=timezone.utc)
            document['updated_at'] = datetime.now(tz=timezone.utc)

            result = await self.collection.insert_one(document, **kwargs)
            logger.debug(f"Inserted document with ID {result.inserted_id} into {self.name}")

            self._invalidate_cache()
            return result.inserted_id
        except Exception as e:
            logger.error(f"Error creating document in {self.name}: {e}")
            raise

    @with_retry(max_retries=3)
    async def create_many(self, documents: List[Dict[str, Any]],
                          ordered: bool = False, **kwargs) -> List[Any]:
        """Insert multiple documents. Returns list of inserted IDs."""
        if not documents:
            return []

        try:
            now = datetime.now(tz=timezone.utc)
            for doc in documents:
                doc['created_at'] = now
                doc['updated_at'] = now

            result = await self.collection.insert_many(documents, ordered=ordered, **kwargs)
            logger.debug(f"Inserted {len(result.inserted_ids)} documents into {self.name}")

            self._invalidate_cache()
            return result.inserted_ids
        except BulkWriteError as bwe:
            logger.error(f"Bulk write error in {self.name}: {bwe.details}")
            inserted = [oid for oid in bwe.details.get('insertedIds', {}).values()]
            # Partial success still wrote documents -> the cache must be invalidated.
            if inserted:
                self._invalidate_cache()
            return inserted
        except Exception as e:
            logger.error(f"Error creating documents in {self.name}: {e}")
            raise

    # READ Operations

    @with_retry(max_retries=2)
    async def find_one(self, filter_dict: Dict[str, Any] = None,
                       projection: Dict[str, Any] = None,
                       cache_key: str = None,
                       cache_duration: int = None,
                       **kwargs) -> Optional[Dict[str, Any]]:
        """Find a single document, hitting the cache first when ``cache_key`` is given."""
        if cache_key:
            cached = self._cache.get(self._ckey(cache_key))
            if cached is not None:
                logger.debug(f"Cache hit for {cache_key} in {self.name}")
                # Copy-on-read: callers must never receive a live reference to the
                # cached document, or a caller's mutation would poison shared state.
                return copy.deepcopy(cached)

        try:
            filter_dict = filter_dict or {}
            result = await self.collection.find_one(filter_dict, projection, **kwargs)

            if cache_key and result:
                duration = cache_duration or self._default_cache_duration
                self._cache.set(self._ckey(cache_key), result, ttl=duration)
                return copy.deepcopy(result)

            return result
        except Exception as e:
            logger.error(f"Error finding document in {self.name}: {e}")
            raise

    @with_retry(max_retries=2)
    async def find_many(self, filter_dict: Dict[str, Any] = None,
                        projection: Dict[str, Any] = None,
                        sort: List[tuple] = None,
                        limit: int = None,
                        skip: int = 0,
                        cache_key: str = None,
                        cache_duration: int = None,
                        **kwargs) -> List[Dict[str, Any]]:
        """Find multiple documents (cursor optimized), hitting the cache first when
        ``cache_key`` is given."""
        if cache_key:
            cached = self._cache.get(self._ckey(cache_key))
            if cached is not None:
                logger.debug(f"Cache hit for {cache_key} in {self.name}")
                # Copy-on-read: hand back a private copy so a caller mutating a
                # returned document cannot corrupt the cached list.
                return copy.deepcopy(cached)

        try:
            filter_dict = filter_dict or {}
            cursor = self.collection.find(filter_dict, projection, **kwargs)

            if sort:
                cursor = cursor.sort(sort)
            if skip > 0:
                cursor = cursor.skip(skip)
            if limit:
                cursor = cursor.limit(limit)

            documents = await cursor.to_list(length=limit)
            logger.debug(f"Found {len(documents)} documents in {self.name}")

            if cache_key:
                duration = cache_duration or self._default_cache_duration
                self._cache.set(self._ckey(cache_key), documents, ttl=duration)
                return copy.deepcopy(documents)

            return documents
        except Exception as e:
            logger.error(f"Error finding documents in {self.name}: {e}")
            raise

    @with_retry(max_retries=2)
    async def count_documents(self, filter_dict: Dict[str, Any] = None, **kwargs) -> int:
        """Count documents matching the filter."""
        try:
            filter_dict = filter_dict or {}
            count = await self.collection.count_documents(filter_dict, **kwargs)
            return count
        except Exception as e:
            logger.error(f"Error counting documents in {self.name}: {e}")
            raise

    @with_retry(max_retries=2)
    async def aggregate(self, pipeline: List[Dict[str, Any]], **kwargs) -> List[Dict[str, Any]]:
        """Perform aggregation pipeline operations."""
        try:
            cursor = await self.collection.aggregate(pipeline, **kwargs)
            results = await cursor.to_list(length=None)
            logger.debug(f"Aggregation returned {len(results)} results from {self.name}")
            return results
        except Exception as e:
            logger.error(f"Error in aggregation for {self.name}: {e}")
            raise

    # UPDATE Operations

    @with_retry(max_retries=3)
    async def update_one(self, filter_dict: Dict[str, Any],
                         update_dict: Dict[str, Any],
                         upsert: bool = False,
                         **kwargs) -> bool:
        """Update a single document. Returns True if modified."""
        try:
            update_dict = self._stamp_update(update_dict)

            result = await self.collection.update_one(filter_dict, update_dict,
                                                      upsert=upsert, **kwargs)

            success = result.modified_count > 0 or (upsert and result.upserted_id is not None)
            if success:
                logger.debug(f"Updated document in {self.name}")
                self._invalidate_cache()

            return success
        except Exception as e:
            logger.error(f"Error updating document in {self.name}: {e}")
            raise

    @with_retry(max_retries=3)
    async def update_many(self, filter_dict: Dict[str, Any],
                          update_dict: Dict[str, Any],
                          **kwargs) -> int:
        """Update multiple documents. Returns count of modified documents."""
        try:
            update_dict = self._stamp_update(update_dict)

            result = await self.collection.update_many(filter_dict, update_dict, **kwargs)

            if result.modified_count > 0:
                logger.debug(f"Updated {result.modified_count} documents in {self.name}")
                self._invalidate_cache()

            return result.modified_count
        except Exception as e:
            logger.error(f"Error updating documents in {self.name}: {e}")
            raise

    @with_retry(max_retries=3)
    async def replace_one(self, filter_dict: Dict[str, Any],
                          replacement: Dict[str, Any],
                          upsert: bool = False,
                          **kwargs) -> bool:
        """Replace a single document. Returns True if replaced."""
        try:
            replacement['updated_at'] = datetime.now(tz=timezone.utc)
            if 'created_at' not in replacement:
                replacement['created_at'] = datetime.now(tz=timezone.utc)

            result = await self.collection.replace_one(filter_dict, replacement,
                                                       upsert=upsert, **kwargs)

            success = result.modified_count > 0 or (upsert and result.upserted_id is not None)
            if success:
                logger.debug(f"Replaced document in {self.name}")
                self._invalidate_cache()

            return success
        except Exception as e:
            logger.error(f"Error replacing document in {self.name}: {e}")
            raise

    # DELETE Operations

    @with_retry(max_retries=3)
    async def delete_one(self, filter_dict: Dict[str, Any], **kwargs) -> bool:
        """Delete a single document. Returns True if deleted."""
        try:
            result = await self.collection.delete_one(filter_dict, **kwargs)

            if result.deleted_count > 0:
                logger.debug(f"Deleted document from {self.name}")
                self._invalidate_cache()
                return True

            return False
        except Exception as e:
            logger.error(f"Error deleting document from {self.name}: {e}")
            raise

    @with_retry(max_retries=3)
    async def delete_many(self, filter_dict: Dict[str, Any], **kwargs) -> int:
        """Delete multiple documents. Returns count of deleted documents."""
        try:
            result = await self.collection.delete_many(filter_dict, **kwargs)

            if result.deleted_count > 0:
                logger.debug(f"Deleted {result.deleted_count} documents from {self.name}")
                self._invalidate_cache()

            return result.deleted_count
        except Exception as e:
            logger.error(f"Error deleting documents from {self.name}: {e}")
            raise

    # BULK Operations

    @with_retry(max_retries=3)
    async def bulk_write(self, operations: List[Union[UpdateOne, InsertOne, DeleteOne, ReplaceOne]],
                         ordered: bool = False, **kwargs) -> Dict[str, Any]:
        """Perform bulk write operations for maximum efficiency."""
        if not operations:
            return {'inserted_count': 0, 'modified_count': 0, 'deleted_count': 0}

        try:
            now = datetime.now(tz=timezone.utc)
            for op in operations:
                # pymongo stores the payload of every write op in `_doc` (there is no
                # `_update` attribute). For UpdateOne it is the update document
                # (operator form); for ReplaceOne it is the full replacement document.
                if isinstance(op, UpdateOne):
                    update_doc = getattr(op, '_doc', None)
                    # Skip aggregation-pipeline updates (a list) -- they take no $set.
                    if isinstance(update_doc, dict):
                        update_doc.setdefault('$set', {})['updated_at'] = now
                elif isinstance(op, ReplaceOne):
                    # Stamp the replacement as a plain field; injecting $set here would
                    # corrupt it into an invalid mixed document.
                    replacement = getattr(op, '_doc', None)
                    if isinstance(replacement, dict):
                        replacement['updated_at'] = now
                elif isinstance(op, InsertOne):
                    if isinstance(getattr(op, '_doc', None), dict):
                        op._doc['created_at'] = now
                        op._doc['updated_at'] = now

            result = await self.collection.bulk_write(operations, ordered=ordered, **kwargs)

            logger.debug(f"Bulk operation completed on {self.name}: "
                         f"inserted={result.inserted_count}, "
                         f"modified={result.modified_count}, "
                         f"deleted={result.deleted_count}")

            if result.inserted_count > 0 or result.modified_count > 0 or result.deleted_count > 0:
                self._invalidate_cache()

            return {
                'inserted_count': result.inserted_count,
                'modified_count': result.modified_count,
                'deleted_count': result.deleted_count,
                'upserted_count': result.upserted_count,
                'upserted_ids': result.upserted_ids
            }
        except BulkWriteError as bwe:
            logger.warning(f"Bulk write error in {self.name}: {bwe.details}")
            result = bwe.details
            return {
                'inserted_count': result.get('nInserted', 0),
                'modified_count': result.get('nModified', 0),
                'deleted_count': result.get('nRemoved', 0),
                'upserted_count': result.get('nUpserted', 0),
                'errors': result.get('writeErrors', [])
            }
        except Exception as e:
            logger.error(f"Error in bulk write for {self.name}: {e}")
            raise

    # CONVENIENCE CAPABILITIES
    #
    # Generic, reusable shapes for the recurring read/write patterns across the
    # ecosystem, so feature code never needs a raw collection handle. Each is a thin
    # wrapper over the CRUD methods above (so they inherit cache invalidation + retry)
    # and is tagged with a one-line ``Capability:`` so the engine's surface is greppable.

    async def upsert_by_field(self, field: str, value: Any,
                              update: Dict[str, Any], **kwargs) -> bool:
        """Capability: upsert-by-identity. Find the doc where ``field == value`` and apply
        ``update`` (upsert). ``update`` may be operator-form (``{"$set": {...}}``) or a plain
        field dict (wrapped in ``$set``). Replaces ``update_one({id: v}, ..., upsert=True)``."""
        update = dict(update)
        if not any(k.startswith("$") for k in update):
            update = {"$set": update}
        return await self.update_one({field: value}, update, upsert=True, **kwargs)

    async def increment_fields(self, filter_dict: Dict[str, Any],
                               fields: Dict[str, Union[int, float]],
                               upsert: bool = True, **kwargs) -> bool:
        """Capability: atomic multi-field ``$inc``. Increment several counters on the matched
        doc in one write (vote tallies, XP, activity counters)."""
        return await self.update_one(filter_dict, {"$inc": dict(fields)}, upsert=upsert, **kwargs)

    async def update_nested_field(self, filter_dict: Dict[str, Any], dotted_path: str,
                                  value: Any, op: str = "$set", upsert: bool = True) -> bool:
        """Capability: nested dotted update. Set/unset/inc a nested field by dotted path
        (``"opted_out_guilds.123"``). Use ``op="$unset"`` (with ``value=""``) to remove it."""
        return await self.update_one(filter_dict, {op: {dotted_path: value}}, upsert=upsert)

    async def push_to_array(self, filter_dict: Dict[str, Any], array_field: str,
                            element: Any, upsert: bool = True, **kwargs) -> bool:
        """Capability: array ``$push``. Append an element to an array field (e.g. a quote's
        ``sent_channels``, an achievement progress list)."""
        return await self.update_one(filter_dict, {"$push": {array_field: element}},
                                     upsert=upsert, **kwargs)

    async def find_top_n(self, filter_dict: Dict[str, Any], sort_field: str, limit: int,
                         *, descending: bool = True,
                         projection: Dict[str, Any] = None, **kwargs) -> List[Dict[str, Any]]:
        """Capability: leaderboard / top-N. The first ``limit`` docs matching ``filter_dict``
        ordered by ``sort_field`` (descending by default)."""
        direction = -1 if descending else 1
        return await self.find_many(filter_dict or {}, projection=projection,
                                    sort=[(sort_field, direction)], limit=limit, **kwargs)

    async def toggle_vote(self, filter_dict: Dict[str, Any], vote_field: str,
                          vote_value: Any) -> Dict[str, Any]:
        """Capability: add/flip/remove a per-user vote. Idempotent toggle over the doc matched
        by ``filter_dict`` (typically ``{entity_id, user_id}``): absent → add; same value →
        remove; different value → change. Returns ``{"action": added|removed|changed,
        "new_value": value|None}``."""
        existing = await self.find_one(filter_dict)
        if existing is None:
            doc = dict(filter_dict)
            doc[vote_field] = vote_value
            await self.create_one(doc)
            return {"action": "added", "new_value": vote_value}
        if existing.get(vote_field) == vote_value:
            await self.delete_one(filter_dict)
            return {"action": "removed", "new_value": None}
        await self.update_one(filter_dict, {"$set": {vote_field: vote_value}})
        return {"action": "changed", "new_value": vote_value}

    async def delete_before_date(self, filter_dict: Dict[str, Any], date_field: str,
                                 cutoff: datetime) -> int:
        """Capability: time-windowed purge. Delete docs matching ``filter_dict`` whose
        ``date_field`` is older than ``cutoff``. Returns the deleted count."""
        query = dict(filter_dict or {})
        query[date_field] = {"$lt": cutoff}
        return await self.delete_many(query)

    async def aggregate_paginated(self, pipeline: List[Dict[str, Any]], *,
                                  page: int = 1, page_size: int = 10) -> Dict[str, Any]:
        """Capability: paged aggregation. Run ``pipeline`` and return one page plus totals:
        ``{"data": [...], "total": int, "page": int, "pages": int, "page_size": int}``."""
        page = max(1, int(page))
        page_size = max(1, int(page_size))
        skip = (page - 1) * page_size
        data = await self.aggregate(list(pipeline) + [{"$skip": skip}, {"$limit": page_size}])
        count_res = await self.aggregate(list(pipeline) + [{"$count": "total"}])
        total = count_res[0]["total"] if count_res else 0
        pages = (total + page_size - 1) // page_size
        return {"data": data, "total": total, "page": page, "pages": pages, "page_size": page_size}

    # UTILITY Methods

    async def create_indexes(self) -> List[str]:
        """Create indexes defined in the collection configuration."""
        if not self.config.indexes:
            return []

        try:
            index_names = await self.collection.create_indexes(self.config.indexes)
            logger.info(f"Created {len(index_names)} indexes for {self.name}: {index_names}")
            return index_names
        except OperationFailure as e:
            # 85 = IndexOptionsConflict, 86 = IndexKeySpecsConflict: an existing index
            # has a different spec than requested. Drop ONLY the conflicting index(es)
            # and recreate them; every other index on the collection is left in place.
            if e.code in (85, 86):
                logger.warning(
                    f"Index spec conflict on {self.name} (code {e.code}); "
                    f"dropping and recreating only the conflicting index(es)."
                )
                return await self._recreate_conflicting_indexes()
            # 13297 = DatabaseDifferCase (e.g. "Admin" vs system "admin"): cannot be
            # fixed client-side; collection reads/writes still work through the driver.
            if e.code == 13297:
                logger.warning(
                    f"Database name case conflict on {self.name} (code 13297); "
                    f"skipping index creation. Collection reads/writes still proceed."
                )
                return []
            logger.error(f"Error creating indexes for {self.name}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating indexes for {self.name}: {e}")
            raise

    async def _recreate_conflicting_indexes(self) -> List[str]:
        """Build indexes one at a time; for any that conflicts (code 85/86), drop the
        existing index with the same name (or, if the name differs, the one with
        matching keys) and recreate just that index. Non-conflicting indexes are
        left untouched."""
        created: List[str] = []
        for index in self.config.indexes:
            spec = index.document  # pymongo always fills in 'name' (auto-generated if unnamed)
            name = spec.get("name")
            try:
                created.extend(await self.collection.create_indexes([index]))
                continue
            except OperationFailure as e:
                if e.code not in (85, 86):
                    raise
            # Resolve the conflict: drop by requested name, else by matching key pattern.
            try:
                await self.collection.drop_index(name)
            except OperationFailure as drop_err:
                if drop_err.code != 27:  # 27 = IndexNotFound (existing index uses a different name)
                    raise
                existing = await self.collection.index_information()
                wanted_key = list(spec["key"].items())
                target = next(
                    (n for n, info in existing.items()
                     if n != "_id_" and info.get("key") == wanted_key),
                    None,
                )
                if target:
                    await self.collection.drop_index(target)
            created.extend(await self.collection.create_indexes([index]))
            logger.info(f"Repaired conflicting index '{name}' on {self.name}")
        return created

    async def drop_indexes(self, index_names: List[str] = None):
        """Drop specified indexes or all non-default indexes."""
        try:
            if index_names:
                for index_name in index_names:
                    await self.collection.drop_index(index_name)
                logger.info(f"Dropped indexes {index_names} from {self.name}")
            else:
                await self.collection.drop_indexes()
                logger.info(f"Dropped all indexes from {self.name}")
        except Exception as e:
            logger.error(f"Error dropping indexes from {self.name}: {e}")
            raise

    async def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        try:
            stats = await self.collection.database.command('collStats', self.name)
            return {
                'count': stats.get('count', 0),
                'size': stats.get('size', 0),
                'avgObjSize': stats.get('avgObjSize', 0),
                'storageSize': stats.get('storageSize', 0),
                'indexes': stats.get('nindexes', 0),
                'totalIndexSize': stats.get('totalIndexSize', 0)
            }
        except Exception as e:
            logger.warning(f"Error getting stats for {self.name}: {e}")
            return {}

    # CACHE Management

    def cache_stats(self) -> Dict[str, Any]:
        """Return the underlying cache backend's statistics."""
        return self._cache.get_stats()
