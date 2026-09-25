"""
FastAPI application entrypoint.

Wiring only: logging, configuration check, middleware, routers, the service
container's lifecycle and the CLI used to launch Uvicorn. All behaviour lives
in ``api``/``services``/``core``.
"""

# Standard library imports
import argparse
import logging
from contextlib import asynccontextmanager
from typing import Callable

# Third-party imports
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables before importing any config-dependent module
load_dotenv()

# Windows-specific asyncio fixes must run before the event loop is created
from utils.asyncio_utils import setup_asyncio_logging, setup_windows_asyncio  # noqa: E402
from utils.uvicorn_config import configure_uvicorn_for_windows, get_uvicorn_config, get_uvicorn_ssl_config  # noqa: E402

setup_windows_asyncio()
setup_asyncio_logging()
configure_uvicorn_for_windows()

from api.container import AppContainer  # noqa: E402
from api.error_handlers import register_error_handlers  # noqa: E402
from api.middleware import (  # noqa: E402
    BodySizeLimitMiddleware,
    IpRateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from api.routes import api_v1_router, health_router  # noqa: E402
from config.settings import Config  # noqa: E402
from core.infrastructure.lifecycle import StartupBanner  # noqa: E402
from utils.logging_setup import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

APP_VERSION = "3.0.0"
#: Headers the web frontend may send cross-origin.
CORS_ALLOWED_HEADERS = ["Authorization", "Content-Type", "X-API-Key", "X-End-User-Id", "X-Request-ID"]
CORS_ALLOWED_METHODS = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]

configure_logging()
Config.validate()


def create_app(container_factory: Callable[[], AppContainer] = AppContainer) -> FastAPI:
    """
    Assemble the FastAPI application.

    Args:
        container_factory: Builds the service container (tests pass one with fakes).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Build every shared service before serving; release them on shutdown."""
        container = container_factory()
        app.state.container = container
        await container.start()
        # Intentional operator-facing console output, not debug logging.
        print(StartupBanner("https" if get_uvicorn_ssl_config() else "http").render())
        yield
        await container.stop()

    app = FastAPI(
        title="RAG Chatbot API",
        description="Knowledge-grounded chatbot: public chat API for frontends and an admin API for the management web.",
        version=APP_VERSION,
        debug=Config.Server.DEBUG(),
        lifespan=lifespan,
        docs_url=None if Config.Server.IS_PRODUCTION() else "/docs",
        redoc_url=None if Config.Server.IS_PRODUCTION() else "/redoc",
        openapi_url=None if Config.Server.IS_PRODUCTION() else "/openapi.json",
    )
    register_error_handlers(app)

    # Starlette runs the last-added middleware first, so this list reads
    # innermost -> outermost; CORS must be outermost so even 401/429/413
    # responses carry CORS headers and preflights never hit authentication.
    app.add_middleware(IpRateLimitMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=Config.Security.CORS_ORIGINS(),
        allow_credentials=False,
        allow_methods=CORS_ALLOWED_METHODS,
        allow_headers=CORS_ALLOWED_HEADERS,
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    app.include_router(health_router)
    app.include_router(api_v1_router)
    return app


app = create_app()


def _build_arg_parser() -> argparse.ArgumentParser:
    """Define the command line interface for launching the server."""
    parser = argparse.ArgumentParser(description="Run the chatbot API server")
    parser.add_argument("--port", type=int, help="Port to run the server on")
    parser.add_argument("--host", type=str, help="Host to bind the server to")
    return parser


def main() -> None:
    """
    Parse CLI arguments and start Uvicorn with a single worker.

    One worker is deliberate: the embedding/reranker models, the knowledge
    index and the rate-limit counters live in process memory.
    """
    args = _build_arg_parser().parse_args()
    uvicorn_config = get_uvicorn_config()
    uvicorn_config.update(get_uvicorn_ssl_config())
    try:
        uvicorn.run(
            "main:app" if Config.Server.DEBUG() else app,
            host=args.host or Config.Server.HOST(),
            port=args.port or Config.Server.PORT(),
            reload=Config.Server.DEBUG(),
            workers=1,
            proxy_headers=True,
            forwarded_allow_ips=Config.Server.FORWARDED_ALLOW_IPS(),
            **uvicorn_config,
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")


if __name__ == "__main__":
    main()
