"""
Reference tool: reports the current date and time.

Kept intentionally trivial (no external calls, no side effects) so it can
serve as the template a new tool copies from: implement the four
``BaseTool`` members, then register an instance with :class:`ToolRegistry`.
"""

# Standard library imports
import logging
from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Local imports
from .base import BaseTool

logger = logging.getLogger(__name__)

#: Timezone used when the model omits the ``timezone`` argument.
_DEFAULT_TIMEZONE = "UTC"


class CurrentTimeTool(BaseTool):
    """Reports the current date and time in an IANA timezone (UTC by default)."""

    @property
    def name(self) -> str:
        return "get_current_time"

    @property
    def description(self) -> str:
        return (
            "Get the current date and time. Use this whenever the user asks "
            "what time or date it is right now, in any timezone."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "IANA timezone name, e.g. 'Asia/Ho_Chi_Minh' or "
                        f"'America/New_York'. Defaults to '{_DEFAULT_TIMEZONE}' "
                        "when omitted."
                    ),
                }
            },
            "required": [],
        }

    def execute(self, **kwargs: Any) -> str:
        """
        Args:
            timezone: Optional IANA timezone name; defaults to ``UTC``.

        Returns:
            ``"<date> <time> (<timezone>)"``, or an ``Error: ...`` string
            naming the invalid timezone if lookup fails.
        """
        timezone_name = kwargs.get("timezone") or _DEFAULT_TIMEZONE
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            logger.warning("Unknown timezone requested by model: %r", timezone_name)
            return f"Error: unknown timezone '{timezone_name}'. Use an IANA timezone name."

        now = datetime.now(zone)
        logger.debug("Resolved current time for %s: %s", timezone_name, now.isoformat())
        return f"{now.strftime('%Y-%m-%d %H:%M:%S')} ({timezone_name})"
