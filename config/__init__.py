"""
Configuration Package
Centralized configuration management organized by domain.
"""

from .settings import Config

# Legacy aliases retained for modules that still import the flat names.
# Prefer `Config.<Group>.<SETTING>()` in new code.
LLMConfig = Config.LLM
ConfidenceConfig = Config.Confidence
ChatConfig = Config.Chat
DoclingConfig = Config.OCR
OCRConfig = Config.OCR
FileConfig = Config.File
RAGConfig = Config.RAG
ServerConfig = Config.Server
LoggingConfig = Config.Logging
HealthConfig = Config.Health
DatabaseConfig = Config.Database

__all__ = [
    "Config",
    "LLMConfig",
    "ConfidenceConfig",
    "ChatConfig",
    "DoclingConfig",
    "OCRConfig",
    "FileConfig",
    "RAGConfig",
    "ServerConfig",
    "LoggingConfig",
    "HealthConfig",
    "DatabaseConfig",
]
