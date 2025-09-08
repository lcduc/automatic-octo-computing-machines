# Standard library imports
import logging
import argparse
from contextlib import asynccontextmanager
import os
from datetime import datetime
from typing import List

# Third-party imports
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables first, before importing any config classes
load_dotenv()

# Local imports - Now import config classes after .env is loaded
from api.routes import router
from config.server.server_config import ServerConfig
from config.server.logging_config import LoggingConfig
from config.llm.llm_config import LLMConfig
from config.file.file_config import FileConfig
from config.rag.rag_config import RAGConfig
from setting import validate_config
from core.rag.embeddings import get_embedding_service
from core.storage.vector_store_optimized import OptimizedVectorStore
from core.monitoring import auto_reload_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger()
    workers = ServerConfig.UVICORN_WORKERS()
    display_host = (
        "localhost" if ServerConfig.HOST() == "0.0.0.0" else ServerConfig.HOST()
    )
    print("\n" + "=" * 60)
    print("🚀 Chatbot")
    print("=" * 60)
    print(f"📡 Server: http://{display_host}:{ServerConfig.PORT()}")
    print(f"🔍 Health Check: http://{display_host}:{ServerConfig.PORT()}/")
    print(f"📚 API Docs: http://{display_host}:{ServerConfig.PORT()}/docs")
    print(f"🤖 OpenAI Model: {LLMConfig.OPENAI_MODEL()}")
    print(f"🧠 Embedding Model: {RAGConfig.EMBEDDING_MODEL()}")
    print(f"📁 Data Directory: {FileConfig.CHUNKS_DIR()}")
    print(f"🧑‍💻 Uvicorn Workers: {workers}")
    print("=" * 60)
    if not LLMConfig.OPENAI_API_KEY():
        print("⚠️  WARNING: OpenAI API key not configured!")
        print("   Please set OPENAI_API_KEY in your .env file")
        print("=" * 60)
    else:
        print("✅ Configuration validated successfully")
        print("=" * 60)
    print("🎯 Ready to process files and answer questions!")
    print("   Press Ctrl+C to stop the server\n")
    # Warm up critical services to avoid first-request latency
    try:
        logger.info("🔥 Warming up embedding model and vector store...")
        embedding_service = get_embedding_service()
        embedder = embedding_service.get_embedder()
        # Tiny warmup encode to initialize model execution graph
        try:
            _ = embedder.encode(["warmup"], convert_to_numpy=True, show_progress_bar=False)
        except Exception:
            # Some models may not accept show_progress_bar; ignore warmup failure
            _ = embedder.encode(["warmup"])  # best-effort

        # Warm up vector store (load HDF5 and FAISS into memory if present)
        try:
            vs = OptimizedVectorStore()
            _ = vs.load_vector_store()
            
            # Setup auto-reload system
            auto_reload_manager.setup_vector_store(vs)
            auto_reload_manager.start_auto_reload()
            logger.info("🔄 Auto-reload system started")
        except Exception as e:
            logger.warning(f"Vector store warmup skipped: {e}")
        logger.info("✅ Warmup complete")
    except Exception as e:
        logger.warning(f"⚠️ Warmup failed: {e}")

    logger.info("Chatbot started successfully\n")
    yield
    print("\n🛑 Shutting down Chatbot...")
    
    # Stop auto-reload system
    try:
        auto_reload_manager.stop_auto_reload()
        logger.info("🔄 Auto-reload system stopped")
    except Exception as e:
        logger.warning(f"⚠️ Error stopping auto-reload: {e}")
    
    print("✅ Shutdown completed. Goodbye!")
    logger.info("Chatbot shutdown complete")

# Create FastAPI app with enhanced configuration
app = FastAPI(
    title="Chatbot",
    description="A scalable RAG chatbot that supports file uploads, URL processing, and web crawling",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    debug=ServerConfig.DEBUG(),
    lifespan=lifespan,
)

# Add CORS middleware with configuration for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=ServerConfig.CORS_ORIGINS(),
    allow_credentials=ServerConfig.CORS_ALLOW_CREDENTIALS(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes from the router module
app.include_router(router)


def main():
    # DEBUG: Print configuration values
    print(f"🔍 DEBUG: ServerConfig.PORT = {ServerConfig.PORT()}")
    print(f"🔍 DEBUG: ServerConfig.HOST = {ServerConfig.HOST()}\n")

    # Ensure log directory exists before any other imports
    log_dir = os.path.join('data', 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # Create log filename with timestamp
    log_filename = f"chatbot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_filepath = os.path.join(log_dir, log_filename)

    # Configure logging as early as possible, force override
    handlers = []
    if LoggingConfig.LOG_TO_FILE():
        handlers.append(logging.FileHandler(log_filepath, encoding="utf-8"))
    handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=getattr(logging, LoggingConfig.LOG_LEVEL().upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True
    )

    logger = logging.getLogger()  # Use root logger
    logger.info("TEST LOG: Main app logging system initialized and writing to file.\n")

    # Add WORKERS config using ServerConfig
    DEFAULT_WORKERS = ServerConfig.UVICORN_WORKERS()

    # Parse command line arguments for runtime configuration override
    parser = argparse.ArgumentParser(description="Run the Chatbot server")
    parser.add_argument("--port", type=int, help="Port to run the server on")
    parser.add_argument("--host", type=str, help="Host to bind the server to")
    parser.add_argument("--workers", type=int, help="Number of Uvicorn workers")
    args = parser.parse_args()

    # Validate configuration on startup
    validate_config()

    # Determine workers
    workers = args.workers if args.workers else DEFAULT_WORKERS

    try:
        # Use command line args if provided, otherwise use config
        host = args.host if args.host else ServerConfig.HOST()
        port = args.port if args.port else ServerConfig.PORT()

        # Determine if we should enable auto-reload (development mode)
        enable_reload = ServerConfig.DEBUG() or ServerConfig.RELOAD()
        
        # Start the server with uvicorn using ServerConfig values
        uvicorn.run("main:app", host=host, port=port, reload=enable_reload, workers=workers)

    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        display_host = (
            "localhost" if ServerConfig.HOST() == "0.0.0.0" else ServerConfig.HOST()
        )
        print(f"\n❌ Error starting server: {e}")
        print(f"\n💡 Alternative command:")
        print(
            f"   uvicorn main:app --host {ServerConfig.HOST()} --port {ServerConfig.PORT()}"
        )
        print(f"   Then visit: http://{display_host}:{ServerConfig.PORT()}")
        logger.error(f"Failed to start server: {e}")
        exit(1)


if __name__ == "__main__":
    main()
