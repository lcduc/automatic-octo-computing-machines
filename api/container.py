"""
Composition root: builds every shared service once, in dependency order.

Models (embeddings, reranker), the database pool and LLM clients are
expensive, so they are created at start-up and shared by all requests.
"""

# Standard library imports
import asyncio
import logging
import time
from typing import Callable, Optional

# Local imports
from config.settings import Config
from core.agent.chatbot import ChatbotService
from core.agent.intent_router import IntentRouter
from core.agent.openai_client import OpenAIClientProvider
from core.agent.provider_factory import LLMProviderFactory
from core.agent.query_rewriter import QueryRewriter
from core.agent.response_cache import ResponseCache
from core.agent.tool_calling_agent import ToolCallingAgent
from core.agent.tools.current_time_tool import CurrentTimeTool
from core.agent.tools.registry import ToolRegistry
from core.guardrails.input_guard import InputGuard
from core.guardrails.pii_redactor import PiiRedactor
from core.retrieval.embeddings import get_embedding_service
from core.retrieval.knowledge_index import KnowledgeIndex
from core.retrieval.retriever import ContextRetriever
from core.storage.database import Database
from services.auth_service import AuthService
from services.chat_service import ChatService
from services.conversation_service import ConversationService
from services.handoff_service import HandoffService
from services.ingestion_service import IngestionService
from services.knowledge_service import KnowledgeService
from services.log_service import LogService
from services.rate_limit_service import RateLimitService
from services.settings_service import SettingsService
from services.transcription_service import TranscriptionService
from services.usage_service import UsageService
from utils.logging_setup import LOG_BACKUP_COUNT, json_log_path

logger = logging.getLogger(__name__)


def _document_processor():
    """Build the Docling-based processor (imported lazily: it is slow to load)."""
    from core.document_processing.main_processor import MainDocumentProcessor

    return MainDocumentProcessor()


class AppContainer:
    """Owns the shared services; ``start``/``stop`` are called by the app lifespan."""

    def __init__(self):
        self.started_at = time.time()
        self.database = Database(Config.Database.DATABASE_URL(), Config.Database.DB_POOL_SIZE())
        self.rate_limiter = RateLimitService()
        self.index = KnowledgeIndex(self.database)
        self.settings = SettingsService(self.database)
        self.usage = UsageService(self.database)
        self.handoffs = HandoffService(self.database, self.usage)
        self.conversations = ConversationService(self.database)
        self.auth = AuthService(
            self.database, Config.Security.ADMIN_JWT_SECRET(), Config.Security.ADMIN_TOKEN_TTL_MINUTES()
        )
        self.logs = LogService(json_log_path(), LOG_BACKUP_COUNT)
        self.redactor = PiiRedactor() if Config.Security.PII_REDACTION_ENABLED() else None
        self.reranker = None
        self.llm = None
        self.pipeline: Optional[ChatbotService] = None
        self.chat: Optional[ChatService] = None
        self.knowledge: Optional[KnowledgeService] = None
        self.transcription: Optional[TranscriptionService] = None

    async def start(self) -> None:
        """Connect, load models, build the pipeline and the first knowledge snapshot."""
        logger.info("Starting services")
        self.database.connect()
        if not await self.database.ping():
            raise RuntimeError("Cannot reach PostgreSQL; check the POSTGRES_* settings")
        await self.settings.load()

        embedding = await self._load_embedding_service()
        self.reranker = await self._load_reranker()
        self.llm = self._create_llm()
        openai = self._openai_extras()
        self.pipeline = self._build_pipeline(embedding, openai)
        self.transcription = TranscriptionService(openai)
        self.chat = ChatService(
            self.database, self.pipeline, self.settings, self.usage, self.handoffs, self.rate_limiter, self.redactor
        )
        ingestion = IngestionService(self._processor_factory(), embedding, Config.OCR.OCR_MAX_CONCURRENT_FILES())
        self.knowledge = KnowledgeService(self.database, ingestion, self.index)

        reembedded = await self.knowledge.reembed_stale_chunks()
        if reembedded:
            logger.info("Re-embedded %d chunks for model %s", reembedded, embedding.model_name)
        await self.index.refresh()
        logger.info("Services started")

    async def _load_embedding_service(self):
        """Load the sentence-transformers model (and optional query adapter) off the event loop."""
        embedding = get_embedding_service()
        await asyncio.to_thread(embedding.get_embedder)
        embedding.load_query_adapter(Config.RAG.QUERY_ADAPTER_PATH())
        return embedding

    async def _load_reranker(self):
        """Load the cross-encoder when reranking is enabled; ``None`` if disabled or unavailable."""
        if not Config.RAG.RERANKING_ENABLED():
            return None
        from core.retrieval.reranker import get_reranker

        reranker = await asyncio.to_thread(get_reranker)
        return reranker if reranker.available() else None

    def _processor_factory(self) -> Callable[[], object]:
        """Factory of the document parser used for uploads."""
        return _document_processor

    def _create_llm(self):
        """The configured chat-completion provider."""
        return LLMProviderFactory.create()

    def _openai_extras(self) -> Optional[OpenAIClientProvider]:
        """
        The OpenAI client used for moderation, tool calling and transcription.

        Reuses the chat provider when it is OpenAI; otherwise a dedicated
        client is created only if an OpenAI key is configured.
        """
        if isinstance(self.llm, OpenAIClientProvider):
            return self.llm
        if Config.LLM.OPENAI_API_KEY():
            return OpenAIClientProvider()
        return None

    def _build_pipeline(self, embedding, openai: Optional[OpenAIClientProvider]) -> ChatbotService:
        """Assemble the chat pipeline with the optional moderation and tool-calling parts."""
        moderator = openai.moderate if (openai is not None and Config.Security.MODERATION_ENABLED()) else None
        intent_router = tool_agent = None
        if Config.LLM.TOOL_CALLING_ENABLED() and openai is not None:
            registry = ToolRegistry(tools=[CurrentTimeTool()])
            intent_router = IntentRouter(self.llm, registry)
            tool_agent = ToolCallingAgent(openai, registry, QueryRewriter(self.llm))
        return ChatbotService(
            llm_provider=self.llm,
            retriever=ContextRetriever(embedding, self.reranker),
            index=self.index,
            guard=InputGuard(moderator),
            cache=ResponseCache(Config.LLM.LLM_CACHE_MAX_ENTRIES(), Config.LLM.LLM_CACHE_TTL()),
            intent_router=intent_router,
            tool_agent=tool_agent,
        )

    async def stop(self) -> None:
        """Finish background writes and release pools."""
        logger.info("Stopping services")
        try:
            if self.knowledge is not None:
                await self.knowledge.wait_for_background_jobs()
            if self.chat is not None:
                await self.chat.wait_for_pending_writes()
        except Exception:
            logger.exception("Error while draining background work")
        if self.llm is not None:
            self.llm.close()
        await self.database.close()
        logger.info("Services stopped")
