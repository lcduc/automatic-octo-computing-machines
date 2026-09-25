"""
Runtime settings editable from the admin web (fallback mode, canned replies, widget look).

Values live in the ``app_settings`` table; anything never saved falls back to
its default (canned replies come from ``core/agent/prompts.py``). The current values are cached in memory so a chat
turn never waits on the database for them.
"""

# Standard library imports
import logging
from typing import Any, Dict, Optional

# Third-party imports
from sqlalchemy import select

# Local imports
from config.settings import Config
from core.agent.prompts import AutoReplies
from core.storage.database import Database
from core.storage.tables.access_tables import AppSetting
from models.chat_turn import FALLBACK_MODES, ChatPolicy
from .errors import InvalidRequestError

logger = logging.getLogger(__name__)

DEFAULT_WIDGET_TITLE = "Trợ lý ảo"
DEFAULT_WIDGET_COLOR = "#0B5FFF"


def _defaults() -> Dict[str, Any]:
    """Defaults for every runtime setting, used until an admin saves a value."""
    return {
        "fallback_mode": Config.Chat.FALLBACK_MODE(),
        "deny_message": AutoReplies.DENY,
        "handoff_message": AutoReplies.HANDOFF,
        "guard_block_message": AutoReplies.GUARD_BLOCK,
        "greeting_message": AutoReplies.GREETING,
        "thanks_message": AutoReplies.THANKS,
        "assistant_instructions": "",
        "widget_title": DEFAULT_WIDGET_TITLE,
        "widget_welcome_message": AutoReplies.WIDGET_WELCOME,
        "widget_primary_color": DEFAULT_WIDGET_COLOR,
        "widget_suggested_questions": [],
    }


#: Keys safe to expose to the public widget.
PUBLIC_WIDGET_KEYS = ("widget_title", "widget_welcome_message", "widget_primary_color", "widget_suggested_questions")


class SettingsService:
    """Reads and writes runtime settings with an in-memory cache."""

    def __init__(self, database: Database):
        """
        Args:
            database: Connected database.
        """
        self._database = database
        self._values: Dict[str, Any] = _defaults()

    async def load(self) -> None:
        """Load saved values over the defaults (called once at start-up)."""
        async with self._database.session() as session:
            result = await session.execute(select(AppSetting))
            saved = {row.key: row.value for row in result.scalars().all()}
        known = {key: value for key, value in saved.items() if key in self._values}
        self._values.update(known)
        logger.info("Runtime settings loaded (%d saved overrides)", len(known))

    def all(self) -> Dict[str, Any]:
        """Every setting with its current value."""
        return dict(self._values)

    def public_widget_config(self) -> Dict[str, Any]:
        """The subset the embeddable widget may read without authentication."""
        return {key: self._values[key] for key in PUBLIC_WIDGET_KEYS}

    def chat_policy(self) -> ChatPolicy:
        """The current chat behaviour as an immutable snapshot for one turn."""
        values = self._values
        return ChatPolicy(
            fallback_mode=values["fallback_mode"],
            deny_message=values["deny_message"],
            handoff_message=values["handoff_message"],
            guard_block_message=values["guard_block_message"],
            greeting_message=values["greeting_message"],
            thanks_message=values["thanks_message"],
            assistant_instructions=values["assistant_instructions"],
        )

    async def update(self, changes: Dict[str, Any], updated_by: Optional[str]) -> Dict[str, Any]:
        """
        Persist changed settings and apply them immediately.

        Args:
            changes: Setting key -> new value (unknown keys are rejected).
            updated_by: Admin e-mail recorded with the change.

        Raises:
            InvalidRequestError: Unknown key or invalid fallback mode.
        """
        unknown = set(changes) - set(self._values)
        if unknown:
            raise InvalidRequestError(f"Unknown settings: {', '.join(sorted(unknown))}")
        if "fallback_mode" in changes and changes["fallback_mode"] not in FALLBACK_MODES:
            raise InvalidRequestError(f"fallback_mode must be one of {', '.join(FALLBACK_MODES)}")

        async with self._database.session() as session:
            for key, value in changes.items():
                await session.merge(AppSetting(key=key, value=value, updated_by=updated_by))
        self._values.update(changes)
        logger.info("Runtime settings updated by %s: %s", updated_by or "system", sorted(changes))
        return self.all()
