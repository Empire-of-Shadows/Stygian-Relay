from typing import Dict, Any, List, Optional
from datetime import datetime, timezone


class SetupState:
    """
    Tracks the state of a single user's setup session for a guild.
    This object is serialized and stored to maintain state between interactions.
    """

    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.step = "welcome"
        self.started_at = datetime.now(timezone.utc)
        self.last_activity = datetime.now(timezone.utc)

        # Data collected during the setup process
        self.master_log_channel: Optional[int] = None
        self.forwarding_rules: List[Dict[str, Any]] = []
        self.current_rule: Optional[Dict[str, Any]] = None
        self.is_editing: bool = False
        self.setup_options: Dict[str, bool] = {
            "advanced_filtering": False,
            "custom_formatting": False,
            "notifications": False
        }

        # References to the interactive UI message for editing
        self.setup_message_id: Optional[int] = None
        self.setup_channel_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the state object into a dictionary for database storage.
        This method is called before saving the session to the database.
        """
        return {
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "step": self.step,
            "started_at": self.started_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "master_log_channel": self.master_log_channel,
            "rules": self.forwarding_rules,
            "current_rule": self.current_rule,
            "is_editing": self.is_editing,
            "setup_options": self.setup_options,
            "setup_message_id": self.setup_message_id,
            "setup_channel_id": self.setup_channel_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SetupState':
        """
        Creates a SetupState instance from a dictionary.
        This method is called when loading a session from the database.
        """
        state = cls(data["guild_id"], data["user_id"])
        state.step = data.get("step", "welcome")
        state.started_at = datetime.fromisoformat(data["started_at"])
        state.last_activity = datetime.fromisoformat(data["last_activity"])
        state.master_log_channel = data.get("master_log_channel")
        state.forwarding_rules = data.get("rules", [])
        state.current_rule = data.get("current_rule")
        state.is_editing = data.get("is_editing", False)
        state.setup_options = data.get("setup_options", {})
        state.setup_message_id = data.get("setup_message_id")
        state.setup_channel_id = data.get("setup_channel_id")
        return state

    def update_activity(self):
        """Updates the last activity timestamp to keep the session alive."""
        self.last_activity = datetime.now(timezone.utc)

    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """
        Checks if the setup session has expired due to inactivity.
        This is used to prevent sessions from being stored indefinitely.
        """
        return (datetime.now(timezone.utc) - self.last_activity).total_seconds() > (timeout_minutes * 60)

    def get_progress(self) -> float:
        """
        Calculates the setup completion progress as a float between 0.0 and 1.0.
        This is used to display a progress bar to the user.
        """
        # The order of steps determines the progress percentage.
        steps = ["welcome", "permissions", "log_channel", "first_rule", "options", "complete"]
        try:
            current_index = steps.index(self.step)
        except ValueError:
            current_index = 0
        # Progress is the ratio of the current step index to the total number of steps before completion.
        return current_index / (len(steps) - 1)