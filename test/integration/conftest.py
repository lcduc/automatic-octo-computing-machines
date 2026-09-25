"""
Fixtures for tests that need a real PostgreSQL + pgvector database.

Set ``TEST_DATABASE_URL`` (e.g. ``postgresql+asyncpg://chatbot:pw@localhost:5432/chatbot_test``)
to run them; they are skipped otherwise. The schema is dropped and recreated
for every test, so never point this at a database holding real data.
"""

import os

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import text

from core.storage.database import Database
from core.storage.tables import Base

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
DEFAULT_SOURCES = ("general", "FAQ", "contracts", "web_data")
FAKE_EMBEDDING_DIM = 64


@pytest_asyncio.fixture
async def database():
    """A connected database with a freshly created schema and default sources."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    db = Database(TEST_DATABASE_URL, pool_size=5)
    db.connect()
    async with db.engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
        for name in DEFAULT_SOURCES:
            await connection.execute(
                text("INSERT INTO knowledge_sources (name, description, priority, enabled) VALUES (:n, '', 1.0, true)"),
                {"n": name},
            )
    yield db
    await db.close()


class FakeEmbeddingService:
    """Deterministic bag-of-words embeddings so tests need no model weights."""

    model_name = "fake-embedding"

    @staticmethod
    def _vector(text_value: str) -> np.ndarray:
        vector = np.zeros(FAKE_EMBEDDING_DIM, dtype=np.float32)
        for word in text_value.lower().split():
            vector[hash(word) % FAKE_EMBEDDING_DIM] += 1.0
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def embed_passages(self, texts):
        return np.vstack([self._vector(t) for t in texts]) if texts else np.zeros((0, 0), np.float32)

    def embed_query(self, query):
        return self._vector(query)


class FakeProcessor:
    """Splits uploaded text files on blank lines instead of running Docling."""

    async def process_file(self, content: bytes, filename: str):
        if filename.endswith(".bad"):
            raise ValueError("No content could be extracted")
        parts = [p.strip() for p in content.decode("utf-8").split("\n\n") if p.strip()]
        return {"documents": parts, "metadata": {}}
