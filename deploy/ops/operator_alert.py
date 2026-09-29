"""
Alerts raised by the ops CLI itself (a failed nightly backup), delivered by
the backend's notifier in a one-off API container, so both share one channel
configuration.
"""

# Standard library imports
import logging

# Local imports
from .compose import Compose
from .runner import CommandError

logger = logging.getLogger(__name__)

#: Seconds allowed for the one-off container to send the alert.
ALERT_TIMEOUT_SECONDS = 180
#: Longest alert body passed on the command line.
MAX_BODY_LENGTH = 1000


class OperatorAlert:
    """Sends one alert through ``scripts.manage send-alert``."""

    def __init__(self, compose: Compose):
        """
        Args:
            compose: The stack on this box.
        """
        self._compose = compose

    def send(self, subject: str, body: str) -> bool:
        """Deliver the alert; returns ``False`` (and logs) when it could not be sent."""
        command = ["python", "-m", "scripts.manage", "send-alert", "--subject", subject, "--body", body[:MAX_BODY_LENGTH]]
        try:
            self._compose.run_once("api", command, timeout=ALERT_TIMEOUT_SECONDS)
        except CommandError:
            logger.exception("Could not send the alert %r", subject)
            return False
        logger.info("Alert sent: %s", subject)
        return True
