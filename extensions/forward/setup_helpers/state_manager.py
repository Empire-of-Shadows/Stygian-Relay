import asyncio
from typing import Dict, Optional, Any
from datetime import datetime, timedelta, timezone

from database import db_core
from ..models.setup_state import SetupState


class SetupStateManager:
    """Manages active setup sessions across the bot."""

    def __init__(self):
        self.active_sessions: Dict[int, SetupState] = {}  # guild_id -> SetupState
        self._lock = asyncio.Lock()

    # ... existing code ...

    async def ensure_collection_exists(self):
        """
        Ensure the setup_sessions collection exists.
        This method is called before any database operation to ensure that the
        collection exists.
        """
        try:
            # Check if collection exists, if not create it
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")

            # Create an index on guild_id for better performance
            await collection.create_index("guild_id")
            await collection.create_index("expires_at")

            print("✅ Setup sessions collection initialized")
        except Exception as e:
            print(f"❌ Failed to initialize setup_sessions collection: {e}")

    async def create_session(self, guild_id: int, user_id: int) -> SetupState:
        """
        Create a new setup session for a guild.
        This method is called when a user starts the setup wizard.
        """
        async with self._lock:
            # Check for existing session
            if guild_id in self.active_sessions:
                existing = self.active_sessions[guild_id]
                if not existing.is_expired():
                    return existing
                # Remove expired session
                await self.cleanup_session(guild_id)

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
        async with self._lock:
            # Ensure collection exists before accessing
            await self.ensure_collection_exists()

            session = self.active_sessions.get(guild_id)
            if session and session.is_expired():
                await self.cleanup_session(guild_id)
                return None

            # If no active session, try loading from database
            if not session:
                session = await self._load_session_from_db(guild_id)
                if session and not session.is_expired():
                    self.active_sessions[guild_id] = session
                    return session

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
                await self.cleanup_session(guild_id)
                return False

            # Apply updates
            for key, value in updates.items():
                if hasattr(session, key):
                    setattr(session, key, value)

            session.update_activity()

            # Update session in database
            await self._save_session_to_db(session)

            return True

    async def cleanup_session(self, guild_id: int) -> bool:
        """
        Clean up a setup session.
        This method is called to clean up a setup session after it has been
        completed or cancelled.
        """
        async with self._lock:
            if guild_id in self.active_sessions:
                # Save final state to database before cleanup
                session = self.active_sessions[guild_id]
                await self._save_session_to_db(session)

                del self.active_sessions[guild_id]

                # Remove from database after successful completion or expiration
                await self._remove_session_from_db(guild_id)

                return True
            return False

    async def cleanup_expired_sessions(self):
        """
        Clean up all expired sessions.
        This method is called periodically to clean up expired sessions.
        """
        async with self._lock:
            expired_guilds = []
            for guild_id, session in self.active_sessions.items():
                if session.is_expired():
                    expired_guilds.append(guild_id)

            for guild_id in expired_guilds:
                # Save expired session state for potential resume
                session = self.active_sessions[guild_id]
                await self._save_session_to_db(session, mark_expired=True)
                del self.active_sessions[guild_id]

            if expired_guilds:
                print(f"Cleaned up {len(expired_guilds)} expired setup sessions")

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
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")

            # Find all active (non-expired) sessions
            current_time = datetime.now(timezone.utc)

            cursor = collection.find({
                "expires_at": {"$gt": current_time},
                "is_expired": {"$ne": True}
            })

            resumed_count = 0
            async for session_data in cursor:
                try:
                    # Recreate SetupState object from stored data
                    session = self._deserialize_session(session_data)

                    if session and not session.is_expired():
                        async with self._lock:
                            self.active_sessions[session.guild_id] = session
                        resumed_count += 1

                except Exception as e:
                    print(f"Failed to resume session for guild {session_data.get('guild_id')}: {e}")
                    # Clean up corrupted session data
                    await collection.delete_one({"_id": session_data.get("_id")})

            if resumed_count > 0:
                print(f"Resumed {resumed_count} setup sessions from database")

        except Exception as e:
            print(f"Error resuming sessions from database: {e}")

    # Database persistence methods implementation
    async def _save_session_to_db(self, session: SetupState, mark_expired: bool = False):
        """
        Save session state to database for persistence.
        This method is called to save the current state of a setup session to
        the database.
        """
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")

            session_data = self._serialize_session(session)

            if mark_expired:
                session_data["is_expired"] = True
                session_data["expired_at"] = datetime.now(timezone.utc)

            # Update existing or insert new
            await collection.update_one(
                {"guild_id": session.guild_id},
                {"$set": session_data},
                upsert=True
            )

        except Exception as e:
            print(f"Error saving session to database for guild {session.guild_id}: {e}")

    async def _load_session_from_db(self, guild_id: int) -> Optional[SetupState]:
        """
        Load session from database.
        This method is called to load a setup session from the database.
        """
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")

            # Find active session for this guild
            session_data = await collection.find_one({
                "guild_id": str(guild_id),
                "expires_at": {"$gt": datetime.now(timezone.utc)}
            })

            if session_data:
                # Convert back to SetupState object
                return SetupState.from_dict(session_data)

            return None

        except Exception as e:
            if "not found" in str(e).lower():
                # Collection doesn't exist, create it
                await self.ensure_collection_exists()
                return None
            else:
                print(f"Error loading session from database: {e}")
                return None

    async def _remove_session_from_db(self, guild_id: int):
        """
        Remove session from database after completion.
        This method is called to remove a setup session from the database after
        it has been completed or cancelled.
        """
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")
            await collection.delete_one({"guild_id": guild_id})

        except Exception as e:
            print(f"Error removing session from database for guild {guild_id}: {e}")

    def _serialize_session(self, session: SetupState) -> Dict:
        """
        Convert SetupState object to dictionary for database storage.
        This method is called to serialize a setup session before it is saved
        to the database.
        """
        try:
            session_data = session.to_dict()
            session_data["updated_at"] = datetime.now(timezone.utc)
            session_data["is_expired"] = False
            return session_data
        except Exception as e:
            print(f"Error serializing session: {e}")
            return {}

    def _deserialize_session(self, session_data: Dict) -> Optional[SetupState]:
        """
        Convert database dictionary back to SetupState object.
        This method is called to deserialize a setup session after it has been
        loaded from the database.
        """
        try:
            return SetupState.from_dict(session_data)
        except Exception as e:
            print(f"Error deserializing session data: {e}")
            return None

    async def cleanup_old_sessions(self, days_old: int = 7):
        """
        Clean up old expired sessions from database.
        This method is called periodically to clean up old expired sessions
        from the database.
        """
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")

            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)

            result = await collection.delete_many({
                "$or": [
                    {"expires_at": {"$lt": cutoff_date}},
                    {"expired_at": {"$lt": cutoff_date}}
                ]
            })

            if result.deleted_count > 0:
                print(f"Cleaned up {result.deleted_count} old setup sessions from database")

        except Exception as e:
            print(f"Error cleaning up old sessions: {e}")

    async def get_database_session_count(self) -> int:
        """
        Get count of sessions stored in database.
        This method is used to get the number of active setup sessions stored
        in the database.
        """
        try:
            collection = db_core.get_collection("discord_forwarding_bot", "setup_sessions")
            return await collection.count_documents({"is_expired": {"$ne": True}})
        except Exception as e:
            print(f"Error getting database session count: {e}")
            return 0


# Global state manager instance
state_manager = SetupStateManager()