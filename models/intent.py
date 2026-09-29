"""
Intent classification result for a chat turn - RAG lookup vs an action/tool call.
"""

# Standard library imports
from enum import Enum


class IntentType(str, Enum):
    """Which engine a chat turn should be routed to."""

    RAG = "rag"
    ACTION = "action"
    #: The request needs a tool only signed-in users may use (ID-11): ask them to log in.
    LOGIN_REQUIRED = "login"
