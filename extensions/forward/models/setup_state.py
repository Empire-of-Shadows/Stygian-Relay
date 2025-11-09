"""
Data models for setup wizard state management.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import discord


class SetupState:
    """Tracks the state of a guild's setup process."""

    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.step = "welcome"  # Current step in setup
        self.started_at = datetime.now(timezone.utc)
        self.last_activity = datetime.now(timezone.utc)

        # Setup data being collected
        self.master_log_channel: Optional[int] = None
        self.forwarding_rules: List[Dict[str, Any]] = []
        self.current_rule: Optional[Dict[str, Any]] = None
        self.setup_options: Dict[str, bool] = {
            "advanced_filtering": False,
            "custom_formatting": False,
            "notifications": False
        }

        # Interactive message references
        self.setup_message_id: Optional[int] = None
        self.setup_channel_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for storage."""
        return {
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "step": self.step,
            "started_at": self.started_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "master_log_channel": self.master_log_channel,
            "forwarding_rules": self.forwarding_rules,
            "current_rule": self.current_rule,
            "setup_options": self.setup_options,
            "setup_message_id": self.setup_message_id,
            "setup_channel_id": self.setup_channel_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SetupState':
        """Create state from dictionary."""
        state = cls(data["guild_id"], data["user_id"])
        state.step = data["step"]
        state.started_at = datetime.fromisoformat(data["started_at"])
        state.last_activity = datetime.fromisoformat(data["last_activity"])
        state.master_log_channel = data["master_log_channel"]
        state.forwarding_rules = data["forwarding_rules"]
        state.current_rule = data["current_rule"]
        state.setup_options = data["setup_options"]
        state.setup_message_id = data["setup_message_id"]
        state.setup_channel_id = data["setup_channel_id"]
        return state

    def update_activity(self):
        """Update the last activity timestamp."""
        self.last_activity = datetime.now(timezone.utc)

    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """Check if the setup session has expired due to inactivity."""
        return (datetime.now(timezone.utc) - self.last_activity).total_seconds() > (timeout_minutes * 60)

    def get_progress(self) -> float:
        """Get setup completion progress (0.0 to 1.0)."""
        steps = ["welcome", "permissions", "log_channel", "first_rule", "options", "complete"]
        current_index = steps.index(self.step) if self.step in steps else 0
        return current_index / (len(steps) - 1)  # -1 because complete is 100%


class SetupStep:
    """Definition of a setup step with its configuration."""

    def __init__(self, name: str, title: str, description: str, required: bool = True):
        self.name = name
        self.title = title
        self.description = description
        self.required = required
        self.completed = False


# Define all setup steps in order
SETUP_STEPS = [
    SetupStep("welcome", "Welcome!", "Let's set up your message forwarding bot.", True),
    SetupStep("permissions", "Permission Check", "Verifying I have the necessary permissions.", True),
    SetupStep("log_channel", "Log Channel Setup", "Set up where I'll send errors and notifications.", True),
    SetupStep("first_rule", "First Forwarding Rule", "Create your first message forwarding rule.", True),
    SetupStep("options", "Optional Features", "Configure additional features.", False),
    SetupStep("complete", "Setup Complete!", "Your bot is ready to use!", True)
]