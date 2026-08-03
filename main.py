"""
FastAPI application entrypoint.

Wiring only: environment loading, middleware, routers, lifecycle hooks and the
CLI used to launch Uvicorn. All behaviour lives in the ``core``/``services``
packages.
"""

# Standard library imports
import argparse
import logging
from contextlib import asynccontextmanager

# Third-party imports
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# Load environment variables before importing any config-dependent module
load_dotenv()

# Windows-specific asyncio fixes must run before the event loop is created
from utils.system import (  # noqa: E402
    configure_logging,
    configure_uvicorn_for_windows,
    get_uvicorn_config,
    get_uvicorn_ssl_config,
    setup_asyncio_logging,
    setup_windows_asyncio,
)

setup_windows_asyncio()
setup_asyncio_logging()
configure_uvicorn_for_windows()

# Local imports  # noqa: E402
from api.middleware import setup_middleware
from api.routes import router
from api.routes.models import router as models_router
from config.settings import Config
from core.infrastructure.lifecycle import ApplicationLifecycle, StartupBanner
from setting import validate_config

logger = logging.getLogger(__name__)

#: Smallest response body (bytes) worth gzipping.
GZIP_MINIMUM_SIZE = 1000
#: Upper bound on worker processes started by the built-in CLI.
MAX_DEFAULT_WORKERS = 2

# Configure logging and required directories at import time so that both entry
# points behave identically: `python main.py` and `uvicorn main:app`.
configure_logging()
validate_config()

_lifecycle = ApplicationLifecycle()


def _display_host() -> str:
    """Host to show in start-up output (``0.0.0.0`` is not clickable)."""
    host = Config.Server.HOST()
    return "localhost" if host == "0.0.0.0" else host


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run the ordered start-up steps, serve, then run shutdown steps."""
    protocol = "https" if get_uvicorn_ssl_config() else "http"
    banner = StartupBanner(protocol, _display_host(), Config.Server.UVICORN_WORKERS())
    # Intentional operator-facing console output, not debug logging.
    print(banner.render())

    await _lifecycle.startup()
    yield
    await _lifecycle.shutdown()


app = FastAPI(
    title="Chatbot",
    description="A scalable RAG chatbot that supports file uploads, URL processing, and web crawling",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    debug=Config.Server.DEBUG(),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.Server.CORS_ORIGINS(),
    allow_credentials=Config.Server.CORS_ALLOW_CREDENTIALS(),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_SIZE)

setup_middleware(
    app,
    enable_rate_limiting=Config.Server.RATE_LIMIT_ENABLED(),
    enable_request_logging=Config.Logging.REQUEST_LOGGING_ENABLED(),
)

app.include_router(router)
app.include_router(models_router)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Define the command line interface for launching the server."""
    parser = argparse.ArgumentParser(description="Run the Chatbot server")
    parser.add_argument("--port", type=int, help="Port to run the server on")
    parser.add_argument("--host", type=str, help="Host to bind the server to")
    parser.add_argument("--workers", type=int, help="Number of Uvicorn workers")
    parser.add_argument(
        "--build-query-adapter",
        action="store_true",
        help="Compute and save a query adapter from eval files, then exit",
    )
    parser.add_argument(
        "--evals-file",
        type=str,
        help="Path to a JSONL or CSV with 'query' and 'positive' columns",
    )
    parser.add_argument(
        "--lambda-reg", type=float, default=1e-3, help="Regularization lambda for adapter"
    )
    return parser


def main() -> None:
    """Parse CLI arguments and start Uvicorn."""
    args = _build_arg_parser().parse_args()

    if args.build_query_adapter:
        _run_query_adapter_build(args)
        return

    host = args.host or Config.Server.HOST()
    port = args.port or Config.Server.PORT()
    workers = args.workers or min(MAX_DEFAULT_WORKERS, Config.Server.UVICORN_WORKERS())

    uvicorn_config = get_uvicorn_config()
    uvicorn_config.update(get_uvicorn_ssl_config())

    try:
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=Config.Server.DEBUG(),
            workers=workers,
            **uvicorn_config,
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception:
        logger.exception("Failed to start server")
        print(
            f"Alternative command:\n"
            f"   uvicorn main:app --host {host} --port {port}\n"
            f"   Then visit: http://{_display_host()}:{port}"
        )
        raise SystemExit(1)


def _run_query_adapter_build(args: argparse.Namespace) -> None:
    """Build the retrieval query adapter and exit."""
    from scripts.build_query_adapter import QueryAdapterBuilder

    if not args.evals_file:
        raise SystemExit("--evals-file is required when using --build-query-adapter")
    try:
        path = QueryAdapterBuilder().build(args.evals_file, args.lambda_reg)
        print(f"Query adapter saved to {path}")
    except Exception:
        logger.exception("Failed to build query adapter")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
