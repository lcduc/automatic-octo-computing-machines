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
from fastapi.middleware.gzip import GZipMiddleware
from dotenv import load_dotenv
import httpx  # used for lightweight, CA-pinned warm-up

# Load environment variables first, before importing any config classes
load_dotenv()

# Setup Windows-specific asyncio fixes before any other imports
from utils.system import (
    setup_windows_asyncio,
    setup_asyncio_logging,
    configure_uvicorn_for_windows,
    get_uvicorn_config,
    get_uvicorn_ssl_config,
)
setup_windows_asyncio()
setup_asyncio_logging()
configure_uvicorn_for_windows()

# Local imports - Now import config classes after .env is loaded
from api.routes import router
from config.settings import Config
from setting import validate_config
from core.ai_services.embeddings.embeddings import get_embedding_service
from core.storage.vector_stores.vector_store_optimized import OptimizedVectorStore
from utils.performance import start_background_tasks, stop_background_tasks
from utils.performance import preload_all_models

# File watching functionality removed

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger()
    workers = Config.Server.UVICORN_WORKERS()
    display_host = (
        "localhost" if Config.Server.HOST() == "0.0.0.0" else Config.Server.HOST()
    )

    # Check if SSL is enabled
    ssl_config = get_uvicorn_ssl_config()
    protocol = "https" if ssl_config else "http"

    print("\n" + "=" * 60)
    print("Chatbot")
    print("=" * 60)
    print(f"Server: {protocol}://{display_host}:{Config.Server.PORT()}")
    print(f"Health Check: {protocol}://{display_host}:{Config.Server.PORT()}/")
    print(f"API Docs: {protocol}://{display_host}:{Config.Server.PORT()}/docs")
    print(f"OpenAI Model: {Config.LLM.OPENAI_MODEL()}")
    print(f"Embedding Model: {Config.LLM.EMBEDDING_MODEL()}")
    print(f"Reranker Model: {Config.LLM.RERANKER_MODEL()}")
    print(f"Data Directory: {Config.Database.CHUNKS_DIR()}")
    print(f"Uvicorn Workers: {workers}")
    print("=" * 60)
    if not Config.LLM.OPENAI_API_KEY():
        print("WARNING: OpenAI API key not configured!")
        print("   Please set OPENAI_API_KEY in your .env file")
        print("=" * 60)
    else:
        print("Configuration validated successfully")
        print("=" * 60)
    print("Ready to process files and answer questions!")
    print("   Press Ctrl+C to stop the server\n")

    # Preload all ML models for maximum performance
    try:
        logger.info("Preloading all ML models...")
        await preload_all_models()
        logger.info("All models preloaded successfully")
    except Exception as e:
        logger.warning(f"Model preloading failed: {e}")

    # Start background tasks for performance optimization
    try:
        await start_background_tasks()
        logger.info("Background tasks started")
    except Exception as e:
        logger.warning(f"Background tasks failed to start: {e}")

    # Warm up critical services to avoid first-request latency
    try:
        logger.info("Warming up embedding model and vector store...")
        embedding_service = get_embedding_service()
        embedder = embedding_service.get_embedder()
        # Tiny warmup encode to initialize model execution graph
        try:
            _ = embedder.encode(
                ["warmup"], convert_to_numpy=True, show_progress_bar=False
            )
        except Exception:
            # Some models may not accept show_progress_bar; ignore warmup failure
            _ = embedder.encode(["warmup"])  # best-effort

        # Warm up vector store (load HDF5 and FAISS into memory if present)
        try:
            vs = OptimizedVectorStore()
            _ = vs.load_vector_store()
            logger.info("Vector store loaded successfully")
        except Exception as e:
            logger.warning(f"Vector store warmup skipped: {e}")

        # --- OpenAI warm-up (lightweight, CA-pinned, tolerant) ---
        try:
            logger.info("Warming up OpenAI API (lightweight reachability check)...")

            # Make sure no self-signed inbound server cert overrides outbound trust:
            for k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
                os.environ.pop(k, None)

            api_key = Config.LLM.OPENAI_API_KEY()
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

            # Debian/Ubuntu CA bundle path inside slim images
            ca_bundle = "/etc/ssl/certs/ca-certificates.crt"

            # Any 2xx–4xx means "reachable" (network/TLS OK). Only network/TLS errors are concerning.
            with httpx.Client(timeout=5, verify=ca_bundle) as client:
                r = client.get("https://api.openai.com/v1/models", headers=headers)

            if 200 <= r.status_code < 500:
                logger.info(
                    "OpenAI reachable (status %s). Warm-up OK.", r.status_code
                )
            else:
                logger.warning(
                    "OpenAI unexpected status %s during warm-up: %s",
                    r.status_code,
                    r.text[:200],
                )
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.warning(
                "OpenAI warm-up network issue (%s). Continuing without blocking.",
                type(e).__name__,
            )
        except Exception as e:
            logger.warning("OpenAI warm-up non-fatal error: %s", e)
        # --- end OpenAI warm-up ---

        logger.info("Warmup complete")
    except Exception as e:
        logger.warning(f"Warmup failed: {e}")

    logger.info("Chatbot started successfully\n")
    yield
    print("\nShutting down Chatbot...")

    # Stop background tasks
    try:
        await stop_background_tasks()
        logger.info("Background tasks stopped")
    except Exception as e:
        logger.warning(f"Error stopping background tasks: {e}")

    print(" Shutdown completed. Goodbye!")
    logger.info("Chatbot shutdown complete")


# Create FastAPI app with enhanced configuration
app = FastAPI(
    title="Chatbot",
    description="A scalable RAG chatbot that supports file uploads, URL processing, and web crawling",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    debug=Config.Server.DEBUG(),
    lifespan=lifespan,
)

# Add CORS middleware with configuration for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.Server.CORS_ORIGINS(),
    allow_credentials=Config.Server.CORS_ALLOW_CREDENTIALS(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add compression middleware for faster responses
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Include API routes from the router module
app.include_router(router)

# Include model status routes
from api.routes.models import router as models_router
app.include_router(models_router)


def main():
    # DEBUG: Print configuration values
    print(f"DEBUG: ServerConfig.PORT = {Config.Server.PORT()}")
    print(f"DEBUG: ServerConfig.HOST = {Config.Server.HOST()}\n")

    # Ensure log directory exists before any other imports
    log_dir = os.path.join("data", "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Create log filename with timestamp
    log_filename = f"chatbot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_filepath = os.path.join(log_dir, log_filename)

    # Configure logging as early as possible, force override
    handlers = []
    if Config.Logging.LOG_TO_FILE():
        handlers.append(logging.FileHandler(log_filepath, encoding="utf-8"))
    handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=getattr(logging, Config.Logging.LOG_LEVEL().upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )

    logger = logging.getLogger()  # Use root logger
    logger.info("TEST LOG: Main app logging system initialized and writing to file.\n")

    # Add WORKERS config using ServerConfig with performance optimization
    DEFAULT_WORKERS = min(2, Config.Server.UVICORN_WORKERS())  # Limit workers

    # Parse command line arguments for runtime configuration override
    parser = argparse.ArgumentParser(description="Run the Chatbot server")
    parser.add_argument("--port", type=int, help="Port to run the server on")
    parser.add_argument("--host", type=str, help="Host to bind the server to")
    parser.add_argument("--workers", type=int, help="Number of Uvicorn workers")
    parser.add_argument(
        "--build-query-adapter",
        action="store_true",
        help="Compute and save a query adapter from eval files",
    )
    parser.add_argument(
        "--evals-file",
        type=str,
        help="Path to a JSONL or CSV with 'query' and 'positive' columns",
    )
    parser.add_argument(
        "--lambda-reg", type=float, default=1e-3, help="Regularization lambda for adapter"
    )
    args = parser.parse_args()

    # Validate configuration on startup
    validate_config()

    # Determine workers
    workers = args.workers if args.workers else DEFAULT_WORKERS

    # Optional: build query adapter and exit
    if args.build_query_adapter:
        try:
            from core.retrieval.query_expansion.query_adapter import (
                build_from_evals,
                save_query_adapter,
            )
            from core.ai_services.embeddings.embeddings import get_embedding_service
            import pandas as pd

            if not args.evals_file:
                raise ValueError(
                    "--evals-file is required when using --build-query-adapter"
                )
            df = (
                pd.read_json(args.evals_file, lines=True)
                if args.evals_file.lower().endswith("jsonl")
                else pd.read_csv(args.evals_file)
            )
            if not {"query", "positive"}.issubset(df.columns):
                raise ValueError("evals file must contain 'query' and 'positive' columns")
            queries = df["query"].astype(str).tolist()
            positives = df["positive"].astype(str).tolist()

            embedder = get_embedding_service().get_embedder()
            adapter = build_from_evals(queries, positives, embedder, args.lambda_reg)
            path = Config.RAG.QUERY_ADAPTER_PATH()
            save_query_adapter(adapter, path)
            print(f"Query adapter saved to {path} (dim={adapter.shape[0]})")
            return
        except Exception as e:
            print(f"Failed to build query adapter: {e}")
            return

    try:
        # Use command line args if provided, otherwise use config
        host = args.host if args.host else Config.Server.HOST()
        port = args.port if args.port else Config.Server.PORT()

        # Determine if we should enable auto-reload (development mode)
        enable_reload = Config.Server.DEBUG()

        # Get uvicorn configuration optimized for Windows
        uvicorn_config = get_uvicorn_config()

        # Get SSL configuration for HTTPS support
        ssl_config = get_uvicorn_ssl_config()

        # Merge configurations
        uvicorn_config.update(ssl_config)

        # Start the server with uvicorn using ServerConfig values and Windows optimizations
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=enable_reload,
            workers=workers,
            **uvicorn_config,
        )

    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        display_host = (
            "localhost" if Config.Server.HOST() == "0.0.0.0" else Config.Server.HOST()
        )
        print(f"\nError starting server: {e}")
        print(f"\nAlternative command:")
        print(
            f"   uvicorn main:app --host {Config.Server.HOST()} --port {Config.Server.PORT()}"
        )
        print(f"   Then visit: http://{display_host}:{Config.Server.PORT()}")
        logger.error(f"Failed to start server: {e}")
        exit(1)


if __name__ == "__main__":
    main()
