"""
Errors and limits shared by the chunking strategies.
"""

#: Longest chunk any strategy may produce as a single piece, in characters.
MAX_CHUNK_CHARS = 20_000


class InvalidChunkingError(ValueError):
    """The chosen strategy cannot chunk this text (e.g. no Q&A pairs found)."""
