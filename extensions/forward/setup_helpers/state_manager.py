import asyncio
import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta, timezone

import pymongo

from database import db_core
from ..models.setup_state import SetupState

logger = logging.getLogger(__name__)

# Wizard inactivity timeout. Must match SetupState.is_expired's default
# so the DB TTL and the in-memory check agree on when a session ends.
SESSION_TIMEOUT_MINUTES = 30


def _expires_at(session: SetupState) -> datetime:
    return session.last_activity + timedelta(minutes=SESSION_TIMEOUT_MINUTES)


class SetupStateManager:
    """Manages active setup sessions across the bot."""

    def __init__(self):
        self.active_sessions: Dict[int, SetupState] = {}  # guild_id -> SetupState
        self._lock = asyncio.Lock()
        self._indexes_ready = False

    async def ensure_collection_exists(self):
        """
        Ensure the setup_sessions collection has its indexes, including a TTL
        on expires_at so the database auto-cleans stale wizard sessions
        without a Python polling loop.
        """
        if self._indexes_ready:
            return
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")
            await collection.create_index("guild_id", unique=True)
            # TTL index: Mongo deletes the document once `expires_at` < now.
            await collection.create_index(
                "expires_at",
                expireAfterSeconds=0,
                name="expires_at_ttl",
            )
            self._indexes_ready = True
            logger.info("✅ Setup sessions collection initialized")
        except pymongo.errors.OperationFailure as e:
            # Index spec collision (e.g. legacy non-TTL index on the same field)
            # — log loudly but don't block setup; ops can drop the old index.
            logger.warning(f"setup_sessions index ensure failed: {e}")
            self._indexes_ready = True
        except Exception as e:
            logger.error(f"❌ Failed to initialize setup_sessions collection: {e}", exc_info=True)

    async def create_session(self, guild_id: int, user_id: int) -> SetupState:
        """
        Create a new setup session for a guild.
        This method is called when a user starts the setup wizard.
        """
        await self.ensure_collection_exists()
        async with self._lock:
            # Check for existing session
            if guild_id in self.active_sessions:
                existing = self.active_sessions[guild_id]
                if not existing.is_expired():
                    return existing
                # Remove expired session
                await self._cleanup_locked(guild_id)

            # Try to load existing session from database first
            existing_session = await self._load_session_from_db(guild_id)
            if existing_session and not existing_session.is_expired():
                self.active_sessions[guild_id] = existing_session
                return existing_session

            # Create new session
            session = SetupState(guild_id, user_id)
            self.active_sessions[guild_id] = session

            # Save session to database for persistence across restarts
            await self._save_session_to_db(session)

            return session

    async def get_session(self, guild_id: int) -> Optional[SetupState]:
        """
        Get an active setup session for a guild.
        This method is called to retrieve the current setup session for a guild.
        """
        await self.ensure_collection_exists()
        async with self._lock:
            session = self.active_sessions.get(guild_id)
            if session and session.is_expired():
                await self._cleanup_locked(guild_id)
                return None

            # If no active session, try loading from database
            if not session:
                session = await self._load_session_from_db(guild_id)
                if session and not session.is_expired():
                    self.active_sessions[guild_id] = session
                    return session
                return None

            return session

    async def update_session(self, guild_id: int, updates: Dict[str, Any]) -> bool:
        """
        Update a setup session with new data.
        This method is called to update the setup session with new data.
        """
        async with self._lock:
            session = self.active_sessions.get(guild_id)
            if not session:
                return False

            # Check if session has expired
            if session.is_expired():
                await self._cleanup_locked(guild_id)
                return False

            # Apply updates
            for key, value in updates.items():
                if hasattr(session, key):
                    setattr(session, key, value)

            session.update_activity()

            # Update session in database (also refreshes the TTL via expires_at)
            await self._save_session_to_db(session)

            return True

    async def cleanup_session(self, guild_id: int) -> bool:
        """
        Clean up a setup session.
        This method is called to clean up a setup session after it has been
        completed or cancelled.
        """
        async with self._lock:
            return await self._cleanup_locked(guild_id)

    async def _cleanup_locked(self, guild_id: int) -> bool:
        """Lock-held cleanup. Caller must hold self._lock."""
        if guild_id in self.active_sessions:
            del self.active_sessions[guild_id]
            await self._remove_session_from_db(guild_id)
            return True
        return False

    async def get_session_count(self) -> int:
        """Get number of active setup sessions."""
        async with self._lock:
            return len(self.active_sessions)

    async def resume_sessions_on_startup(self):
        """
        Resume active sessions from database on bot startup.
        This method is called when the bot starts up to resume any active
        sessions that were interrupted.
        """
        await self.ensure_collection_exists()
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")

            current_time = datetime.now(timezone.utc)
            cursor = collection.find({"expires_at": {"$gt": current_time}})

            resumed_count = 0
            async for session_data in cursor:
                try:
                    session = self._deserialize_session(session_data)
                    if session and not session.is_expired():
                        async with self._lock:
                            self.active_sessions[session.guild_id] = session
                        resumed_count += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to resume session for guild {session_data.get('guild_id')}: {e}"
                    )
                    await collection.delete_one({"_id": session_data.get("_id")})

            if resumed_count > 0:
                logger.info(f"Resumed {resumed_count} setup sessions from database")

        except Exception as e:
            logger.error(f"Error resuming sessions from database: {e}", exc_info=True)

    # Database persistence methods implementation
    async def _save_session_to_db(self, session: SetupState):
        """Save session state to database for persistence."""
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")

            session_data = self._serialize_session(session)

            # Ensure expires_at is a real datetime — Mongo TTL ignores anything else.
            await collection.update_one(
                {"guild_id": session.guild_id},
                {"$set": session_data},
                upsert=True
            )

        except Exception as e:
            logger.error(
                f"Error saving session to database for guild {session.guild_id}: {e}",
                exc_info=True,
            )

    async def _load_session_from_db(self, guild_id: int) -> Optional[SetupState]:
        """Load an unexpired session from the database, or None."""
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")

            session_data = await collection.find_one({
                "guild_id": guild_id,
                "expires_at": {"$gt": datetime.now(timezone.utc)},
            })

            if session_data:
                return SetupState.from_dict(session_data)

            return None

        except Exception as e:
            logger.error(f"Error loading session from database: {e}", exc_info=True)
            return None

    async def _remove_session_from_db(self, guild_id: int):
        """Remove session from database after completion."""
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")
            await collection.delete_one({"guild_id": guild_id})
        except Exception as e:
            logger.error(
                f"Error removing session from database for guild {guild_id}: {e}",
                exc_info=True,
            )

    def _serialize_session(self, session: SetupState) -> Dict:
        """
        Convert SetupState to a Mongo doc. Adds the expires_at + updated_at
        fields the persistence layer needs but the in-memory state object
        doesn't carry.
        """
        try:
            session_data = session.to_dict()
            session_data["updated_at"] = datetime.now(timezone.utc)
            session_data["expires_at"] = _expires_at(session)
            return session_data
        except Exception as e:
            logger.error(f"Error serializing session: {e}", exc_info=True)
            return {}

    def _deserialize_session(self, session_data: Dict) -> Optional[SetupState]:
        """Convert database dictionary back to SetupState object."""
        try:
            return SetupState.from_dict(session_data)
        except Exception as e:
            logger.error(f"Error deserializing session data: {e}", exc_info=True)
            return None

    async def get_database_session_count(self) -> int:
        """Count of unexpired sessions in the database."""
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")
            return await collection.count_documents(
                {"expires_at": {"$gt": datetime.now(timezone.utc)}}
            )
        except Exception as e:
            logger.error(f"Error getting database session count: {e}", exc_info=True)
            return 0


# Global state manager instance
state_manager = SetupStateManager()
