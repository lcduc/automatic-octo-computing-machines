"""
Runtime settings editable from the admin web (fallback mode, canned replies,
widget look, chat models and retrieval tuning).

Values live in the ``app_settings`` table; anything never saved falls back to
its default (canned replies come from ``core/agent/prompts.py``). The current values are cached in memory so a chat
turn never waits on the database for them.
"""

# Standard library imports
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

# Third-party imports
from sqlalchemy import delete, select

# Local imports
from config.settings import Config
from core.agent.prompts import AutoReplies
from core.storage.database import Database
from core.storage.tables.access_tables import AppSetting
from models.chat_turn import FALLBACK_MODES, ChatPolicy
from models.usage_policy import UsagePolicy
from .business_calendar import DEFAULT_HOLIDAYS, DEFAULT_SUPPORT_HOURS, BusinessCalendar, CalendarError
from .errors import InvalidRequestError

logger = logging.getLogger(__name__)

DEFAULT_WIDGET_TITLE = "Trợ lý ảo"
#: Working hours within which a ticket should be answered (HND-14).
DEFAULT_TICKET_REPLY_HOURS = 8
#: Topics that always go to a human when handoff is on (HND-06); matched without accents.
DEFAULT_HANDOFF_TOPICS = [
    # Whole phrases only: "kiện" alone also means "parcel" (kiện hàng).
    "khiếu nại", "tranh chấp", "luật sư", "khởi kiện", "kiện tụng", "đi kiện", "hoàn tiền", "lừa đảo", "bồi thường",
    "complaint", "lawyer", "lawsuit", "refund", "chargeback", "fraud",
]
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
        "chat_model": Config.LLM.ACTIVE_MODEL(),
        "light_model": Config.LLM.ACTIVE_LIGHT_MODEL(),
        "similarity_threshold": Config.RAG.SIMILARITY_THRESHOLD(),
        "semantic_weight": Config.RAG.SEMANTIC_WEIGHT(),
        "retrieval_top_k": Config.RAG.RETRIEVAL_TOP_K(),
        "max_context_chunks": Config.RAG.MAX_CONTEXT_CHUNKS(),
        "limit_anonymous_per_minute": Config.Security.RATE_LIMIT_ANONYMOUS_PER_MINUTE(),
        "limit_anonymous_per_hour": Config.Security.RATE_LIMIT_ANONYMOUS_PER_HOUR(),
        "tokens_anonymous_per_day": Config.Security.TOKEN_BUDGET_ANONYMOUS_PER_DAY(),
        "limit_user_per_minute": Config.Security.RATE_LIMIT_USER_PER_MINUTE(),
        "limit_user_per_hour": Config.Security.RATE_LIMIT_USER_PER_HOUR(),
        "tokens_user_per_day": Config.Security.TOKEN_BUDGET_USER_PER_DAY(),
        "tokens_ip_per_day": Config.Security.TOKEN_BUDGET_IP_PER_DAY(),
        "spend_cap_monthly_usd": Config.Security.SPEND_CAP_MONTHLY_USD(),
        "spend_anonymous_cutoff_ratio": Config.Security.SPEND_ANONYMOUS_CUTOFF_RATIO(),
        "support_hours": dict(DEFAULT_SUPPORT_HOURS),
        "support_holidays": list(DEFAULT_HOLIDAYS),
        "ticket_reply_hours": DEFAULT_TICKET_REPLY_HOURS,
        "handoff_topics": list(DEFAULT_HANDOFF_TOPICS),
    }


#: Settings naming an LLM; a new value is tried against the provider before it is saved.
MODEL_KEYS = ("chat_model", "light_model")
#: Checks a model name works with the provider; raises when it does not.
ModelCheck = Callable[[str], Awaitable[None]]


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
            chat_model=values["chat_model"],
            light_model=values["light_model"],
            similarity_threshold=values["similarity_threshold"],
            semantic_weight=values["semantic_weight"],
            retrieval_top_k=values["retrieval_top_k"],
            max_context_chunks=values["max_context_chunks"],
            handoff_topics=tuple(values["handoff_topics"]),
        )

    def support_calendar(self) -> BusinessCalendar:
        """Support working hours and holidays (validated when saved)."""
        return BusinessCalendar(self._values["support_hours"], self._values["support_holidays"], Config.Server.APP_TIMEZONE())

    def ticket_reply_hours(self) -> float:
        """Working hours within which a ticket should be answered."""
        return float(self._values["ticket_reply_hours"])

    def usage_policy(self) -> UsagePolicy:
        """Current request limits, token budgets and spend cap."""
        values = self._values
        return UsagePolicy(
            anonymous_per_minute=int(values["limit_anonymous_per_minute"]),
            anonymous_per_hour=int(values["limit_anonymous_per_hour"]),
            anonymous_tokens_per_day=int(values["tokens_anonymous_per_day"]),
            user_per_minute=int(values["limit_user_per_minute"]),
            user_per_hour=int(values["limit_user_per_hour"]),
            user_tokens_per_day=int(values["tokens_user_per_day"]),
            ip_tokens_per_day=int(values["tokens_ip_per_day"]),
            spend_cap_usd=float(values["spend_cap_monthly_usd"]),
            anonymous_cutoff_ratio=float(values["spend_anonymous_cutoff_ratio"]),
        )

    @staticmethod
    def defaults() -> Dict[str, Any]:
        """What every setting falls back to (``.env`` and built-in defaults)."""
        return _defaults()

    async def update(
        self, changes: Dict[str, Any], updated_by: Optional[str], model_check: Optional[ModelCheck] = None
    ) -> Dict[str, Any]:
        """
        Persist changed settings and apply them immediately.

        Args:
            changes: Setting key -> new value (unknown keys are rejected).
            updated_by: Admin e-mail recorded with the change.
            model_check: Tries a new model name against the provider; without
                it model names are saved unchecked.

        Raises:
            InvalidRequestError: Unknown key, invalid fallback mode, or a model
                the provider rejects (nothing is saved then).
        """
        unknown = set(changes) - set(self._values)
        if unknown:
            raise InvalidRequestError(f"Unknown settings: {', '.join(sorted(unknown))}")
        if "fallback_mode" in changes and changes["fallback_mode"] not in FALLBACK_MODES:
            raise InvalidRequestError(f"fallback_mode must be one of {', '.join(FALLBACK_MODES)}")
        if "support_hours" in changes or "support_holidays" in changes:
            try:
                BusinessCalendar.validate(
                    changes.get("support_hours", self._values["support_hours"]),
                    changes.get("support_holidays", self._values["support_holidays"]),
                )
            except CalendarError as exc:
                raise InvalidRequestError(str(exc)) from exc
        if model_check is not None:
            for key in MODEL_KEYS:
                if key in changes and changes[key] != self._values[key]:
                    await self._check_model(model_check, changes[key])

        async with self._database.session() as session:
            for key, value in changes.items():
                await session.merge(AppSetting(key=key, value=value, updated_by=updated_by))
        self._values.update(changes)
        logger.info("Runtime settings updated by %s: %s", updated_by or "system", sorted(changes))
        return self.all()

    @staticmethod
    async def _check_model(model_check: ModelCheck, model: str) -> None:
        """
        Raises:
            InvalidRequestError: The provider cannot answer with ``model``.
        """
        try:
            await model_check(model)
        except Exception as exc:
            logger.exception("Model %s failed its check; not saving it", model)
            raise InvalidRequestError(f"Model not available: {model} ({type(exc).__name__}: {exc})"[:500]) from exc

    async def reset(self, key: str, updated_by: Optional[str]) -> Dict[str, Any]:
        """
        Drop the saved value of ``key`` so its default applies again.

        Raises:
            InvalidRequestError: Unknown key.
        """
        defaults = _defaults()
        if key not in defaults:
            raise InvalidRequestError(f"Unknown setting: {key}")
        async with self._database.session() as session:
            await session.execute(delete(AppSetting).where(AppSetting.key == key))
        self._values[key] = defaults[key]
        logger.info("Runtime setting %s reset to its default by %s", key, updated_by or "system")
        return self.all()
