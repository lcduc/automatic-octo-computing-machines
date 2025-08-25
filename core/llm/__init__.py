"""
LLM (Large Language Model) package - RAG-powered conversation engine.
Provides AI response generation with context retrieval and confidence scoring.
"""

# Import main components for LLM functionality
from .chatbot import ChatbotService
from .prompts import PromptManager, SystemPrompts

# Export main components and utilities
__all__ = [
    "ChatbotService",  # Main chatbot service
    "PromptManager",  # Prompt management
    "SystemPrompts",  # System prompt templates
]
