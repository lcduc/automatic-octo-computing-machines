"""Chunking strategies that split a document's extracted text into retrievable chunks."""

from .chunker import STRATEGY_DESCRIPTIONS, Chunker
from .errors import MAX_CHUNK_CHARS, InvalidChunkingError

__all__ = ["Chunker", "InvalidChunkingError", "MAX_CHUNK_CHARS", "STRATEGY_DESCRIPTIONS"]
