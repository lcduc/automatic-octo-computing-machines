"""
Intent classification result for a chat turn - RAG lookup vs an action/tool call.
"""

# Standard library imports
from enum import Enum


class IntentType(str, Enum):
    """Which engine a chat turn should be routed to."""

    RAG = "rag"
    ACTION = "action"
