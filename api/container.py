"""
Composition root: builds every shared service once, in dependency order.

Models (embeddings, reranker), the database pool and LLM clients are
expensive, so they are created at start-up and shared by all requests.
"""

# Standard library imports
import asyncio
import logging
import time
from typing import Callable, List, Optional

# Local imports
from config.settings import Config
from config.tool_settings import BusinessDbConfig
from core.agent.chatbot import ChatbotService
from core.agent.intent_router import IntentRouter
from core.agent.openai_client import OpenAIClientProvider
from core.agent.provider_factory import LLMProviderFactory
from core.agent.query_rewriter import QueryRewriter
from core.agent.response_cache import ResponseCache
from core.agent.tool_calling_agent import ToolCallingAgent
from core.agent.tools.current_time_tool import CurrentTimeTool
from core.agent.tools.registry import ToolRegistry
from core.agent.tools.sql_tool_executor import SqlToolExecutor
from core.guardrails.input_guard import InputGuard
from core.guardrails.pii_redactor import PiiRedactor
from core.retrieval.remote_models import RemoteReranker, embedding_service, model_server_client
from core.retrieval.knowledge_index import KnowledgeIndex
from core.retrieval.retriever import ContextRetriever
from core.storage.database import Database
from core.storage.upload_store import UploadStore
from services.audit_service import AuditService
from services.auth_service import SERVICE_BFF, AuthService
from services.chat_service import ChatService
from services.conversation_service import ConversationService
from services.handoff_service import HandoffService
from services.host_identity_service import HostIdentityService
from services.ingestion_service import IngestionService
from services.ingestion_worker import IngestionWorker
from services.knowledge_service import KnowledgeService
from services.log_service import LogService
from services.live_feed_service import LiveFeedService, asyncpg_dsn
from services.pricing_service import PricingService
from services.rate_limit_service import RateLimitService, TimeBuckets
from services.readiness_service import ReadinessService
from services.settings_service import SettingsService
from services.sql_tool_catalog import SqlToolCatalog
from services.transcription_service import TranscriptionService
from services.usage_service import UsageService
from utils.logging_setup import LOG_BACKUP_COUNT, json_log_path

logger = logging.getLogger(__name__)

#: Seconds between checks for uploads the ingestion worker has finished.
INGESTION_WATCH_SECONDS = 5
#: Prompt sent once to confirm a newly chosen model exists before it is saved.
MODEL_CHECK_PROMPT = "Reply with OK."


def _document_processor():
    """Build the Docling-based processor (imported lazily: it is slow to load)."""
    from core.document_processing.main_processor import MainDocumentProcessor

    return MainDocumentProcessor()


class AppContainer:
    """Owns the shared services; ``start``/``stop`` are called by the app lifespan."""

    def __init__(self):
        self.started_at = time.time()
        self.database = Database(Config.Database.DATABASE_URL(), Config.Database.DB_POOL_SIZE())
        self.rate_limiter = RateLimitService(self.database, TimeBuckets(Config.Server.APP_TIMEZONE()))
        self.index = KnowledgeIndex(self.database, self._document_tier_level)
        self.settings = SettingsService(self.database)
        self.usage = UsageService(self.database, self.rate_limiter)
        self.pricing = PricingService(self.database)
        self.live_feed = LiveFeedService(self.database, asyncpg_dsn(Config.Database.DATABASE_URL()))
        self.handoffs = HandoffService(self.database, self.live_feed)
        self.conversations = ConversationService(self.database)
        self.auth = AuthService(
            self.database,
            Config.Security.ADMIN_JWT_SECRET(),
            Config.Security.ADMIN_TOKEN_TTL_MINUTES(),
            service_tokens={SERVICE_BFF: Config.Security.BFF_SERVICE_TOKEN()},
        )
        self.host_identity = HostIdentityService.from_config(self.database)
        self.logs = LogService(json_log_path(), LOG_BACKUP_COUNT)
        self.audit = AuditService(self.database)
        self.redactor = PiiRedactor() if Config.Security.PII_REDACTION_ENABLED() else None
        #: Set when the GPU models live in the model-server (MODEL_SERVER_URL).
        self.model_server = model_server_client()
        self.readiness = ReadinessService(self.database, self.model_server)
        #: The client's business database (read-only role) behind the SQL tools; ``None`` without one.
        self.business_database: Optional[Database] = None
        self.sql_tools: Optional[SqlToolCatalog] = None
        if BusinessDbConfig.BUSINESS_DB_URL():
            self.business_database = Database(BusinessDbConfig.BUSINESS_DB_URL(), BusinessDbConfig.BUSINESS_DB_POOL_SIZE())
            executor = SqlToolExecutor(self.business_database, BusinessDbConfig.SQL_TOOL_STATEMENT_TIMEOUT_MS())
            self.sql_tools = SqlToolCatalog(self.database, executor, self.host_identity.tier_level)
        self.reranker = None
        self.llm = None
        self.pipeline: Optional[ChatbotService] = None
        self.chat: Optional[ChatService] = None
        self.knowledge: Optional[KnowledgeService] = None
        self.ingestion_worker: Optional[IngestionWorker] = None
        self.transcription: Optional[TranscriptionService] = None
        self._background_loops: List[asyncio.Task] = []

    def _document_tier_level(self, tier: str) -> int:
        """Access level of a document tier (the host's tiers; unknown ones are unreachable)."""
        return self.host_identity.tier_level(tier)

    async def start(self) -> None:
        """Connect, load models, build the pipeline and the first knowledge snapshot."""
        logger.info("Starting services")
        self.database.connect()
        if not await self.database.ping():
            raise RuntimeError("Cannot reach PostgreSQL; check the POSTGRES_* settings")
        await self.settings.load()
        await self.pricing.load()
        await self.live_feed.start()
        if self.sql_tools is not None:
            self.business_database.connect()
            await self.sql_tools.load()

        embedding = await self._load_embedding_service()
        self.reranker = await self._load_reranker()
        self.llm = self._create_llm()
        openai = self._openai_extras()
        self.pipeline = self._build_pipeline(embedding, openai)
        self.transcription = TranscriptionService(openai)
        self.chat = ChatService(
            self.database, self.pipeline, self.settings, self.usage, self.handoffs, self.pricing, self.live_feed,
            self.redactor,
        )
        ingestion = IngestionService(self._processor_factory(), embedding, Config.OCR.OCR_MAX_CONCURRENT_FILES())
        uploads = UploadStore(Config.Paths.UPLOAD_DIR())
        if Config.OCR.INGESTION_WORKER() == "embedded":
            self.ingestion_worker = IngestionWorker(
                self.database, ingestion, uploads, Config.OCR.OCR_MAX_CONCURRENT_FILES()
            )
        on_upload = self.ingestion_worker.wake if self.ingestion_worker else None
        self.knowledge = KnowledgeService(self.database, ingestion, self.index, uploads, on_upload)

        reembedded = await self.knowledge.reembed_stale_chunks()
        if reembedded:
            logger.info("Re-embedded %d chunks for model %s", reembedded, embedding.model_name)
        # Record the ingestion mark before the first snapshot so no upload finishing in between is missed.
        await self.knowledge.refresh_index_if_ingested()
        await self.index.refresh()
        self._start_background_loops()
        logger.info("Services started")

    def _start_background_loops(self) -> None:
        """Watch for finished uploads and, in embedded mode, run the ingestion worker in this process."""
        self._background_loops.append(
            asyncio.create_task(self.knowledge.watch_ingestions(INGESTION_WATCH_SECONDS))
        )
        if self.ingestion_worker is not None:
            self._background_loops.append(asyncio.create_task(self.ingestion_worker.run()))
        else:
            logger.info("INGESTION_WORKER=external: uploads are parsed by worker.py")

    async def _load_embedding_service(self):
        """
        The embedding service: the model-server's, or the in-process model (and
        optional query adapter) loaded off the event loop.
        """
        embedding = embedding_service(self.model_server)
        await asyncio.to_thread(embedding.get_embedder)
        embedding.load_query_adapter(Config.RAG.QUERY_ADAPTER_PATH())
        return embedding

    async def _load_reranker(self):
        """The cross-encoder when reranking is enabled; ``None`` if disabled or unavailable."""
        if not Config.RAG.RERANKING_ENABLED():
            return None
        if self.model_server is not None:
            status = await asyncio.to_thread(self.model_server.ready)
            return RemoteReranker(self.model_server, bool(status["models"]["reranker"]))
        from core.retrieval.reranker import get_reranker

        reranker = await asyncio.to_thread(get_reranker)
        return reranker if reranker.available() else None

    def _processor_factory(self) -> Callable[[], object]:
        """Factory of the document parser used for uploads."""
        return _document_processor

    def _create_llm(self):
        """The configured chat-completion provider."""
        return LLMProviderFactory.create()

    async def check_model(self, model: str) -> None:
        """
        Answer one tiny prompt with ``model`` on the chat provider.

        Raises:
            Exception: Whatever the provider raises for an unknown or unavailable model.
        """
        await self.llm.complete_async([{"role": "user", "content": MODEL_CHECK_PROMPT}], model=model)

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
            registry = ToolRegistry(tools=[CurrentTimeTool()], source=self.sql_tools)
            intent_router = IntentRouter(self.llm, registry, login_available=self.host_identity.enabled)
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
            # Cancelling the worker hands its unfinished upload back to the queue.
            for task in self._background_loops:
                task.cancel()
            await asyncio.gather(*self._background_loops, return_exceptions=True)
            self._background_loops = []
            if self.chat is not None:
                await self.chat.wait_for_pending_writes()
            await self.live_feed.stop()
        except Exception:
            logger.exception("Error while draining background work")
        if self.llm is not None:
            self.llm.close()
        if self.model_server is not None:
            self.model_server.close()
        if self.business_database is not None:
            await self.business_database.close()
        await self.database.close()
        logger.info("Services stopped")
