"""
Legacy configuration shim.

Kept so existing imports of ``from setting import validate_config`` keep working.
New code should use ``from config.settings import Config`` directly.
"""

# Standard library imports
from dotenv import load_dotenv

load_dotenv()

# Local imports
from config.settings import Config


def validate_config() -> bool:
    """Validate critical configuration settings and create required directories."""
    return Config.validate()
