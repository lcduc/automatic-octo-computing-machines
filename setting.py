# Standard library imports
import os
from dotenv import load_dotenv

# Load environment variables first, before importing any config classes
load_dotenv()

# Import new config classes (after .env is loaded)
from config.llm.llm_config import LLMConfig
from config.server.server_config import ServerConfig
from config.server.logging_config import LoggingConfig
from config.file.file_config import FileConfig
from config.rag.rag_config import RAGConfig
from config.rag.query_expansion_config import VietnamesePreprocessingConfig
from config.llm.confidence_config import ConfidenceConfig
from config.file.url_config import URLConfig
from config.server.health_config import HealthConfig

# Note: OpenAI client is now initialized per-request in the chatbot service
# This avoids the deprecated openai.api_key global configuration

# Directory validation utility
from utils import FileUtils


def validate_config():
    """Validate critical configuration settings and create necessary directories."""
    logger = __import__('logging').getLogger(__name__)

    # Check for required OpenAI API key
    if not LLMConfig.OPENAI_API_KEY():
        logger.warning(
            "⚠️ Warning: OPENAI_API_KEY not set. Chat functionality may not work."
        )
        return False

    # Create necessary directories using FileUtils
    directories = [
        FileConfig.CHUNKS_DIR(),
        FileConfig.VECTORS_DIR(),
        FileConfig.TEMP_DIR(),
    ]
    for directory in directories:
        FileUtils.ensure_directory_exists(directory)
    # Ensure parent directory for vector store exists
    FileUtils.ensure_directory_exists(os.path.dirname(FileConfig.VECTOR_STORE_PATH()))
    return True


# Validate configuration on import
validate_config()


class Config:
    # Aggregated config classes
    LLMConfig = LLMConfig
    ServerConfig = ServerConfig
    LoggingConfig = LoggingConfig
    FileConfig = FileConfig
    RAGConfig = RAGConfig
    VietnamesePreprocessingConfig = VietnamesePreprocessingConfig
    ConfidenceConfig = ConfidenceConfig
    URLConfig = URLConfig
    HealthConfig = HealthConfig
