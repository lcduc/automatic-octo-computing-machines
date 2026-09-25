"""
Human-readable start-up summary printed to the console once the API is ready.

Service construction and shutdown live in ``api.container.AppContainer``.
"""

# Local imports
from config.settings import Config

BANNER_WIDTH = 60


class StartupBanner:
    """Renders the operator-facing start-up summary."""

    def __init__(self, protocol: str):
        """
        Args:
            protocol: ``http`` or ``https`` depending on the TLS configuration.
        """
        self._protocol = protocol

    def render(self) -> str:
        """Build the banner text."""
        host = Config.Server.HOST()
        display_host = "localhost" if host == "0.0.0.0" else host
        base_url = f"{self._protocol}://{display_host}:{Config.Server.PORT()}"
        separator = "=" * BANNER_WIDTH
        lines = [
            separator,
            f"Chatbot API ready ({Config.Server.APP_ENV()})",
            separator,
            f"API:             {base_url}/api/v1",
            f"Readiness:       {base_url}/health/ready",
            f"LLM:             {Config.LLM.LLM_PROVIDER()} / {Config.LLM.ACTIVE_MODEL()}",
            f"Embedding model: {Config.LLM.EMBEDDING_MODEL()}",
            f"Reranker model:  {Config.RAG.RERANKER_MODEL() if Config.RAG.RERANKING_ENABLED() else 'disabled'}",
            f"Database:        {Config.Database.POSTGRES_HOST()}:{Config.Database.POSTGRES_PORT()}/{Config.Database.POSTGRES_DB()}",
        ]
        if not Config.Server.IS_PRODUCTION():
            lines.append(f"API docs:        {base_url}/docs")
        issues = Config.problems()
        lines.append(separator)
        lines.extend(f"WARNING: {issue}" for issue in issues)
        if issues:
            lines.append(separator)
        return "\n".join(lines)
