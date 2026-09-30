"""Retrieval never returns documents the caller may not see, or that are not in force (Invariant 4, EVAL-09)."""

import uuid
from datetime import date

import numpy as np
import pytest

from core.retrieval.knowledge_index import KnowledgeSnapshot
from core.retrieval.retriever import ContextRetriever
from core.storage.knowledge_repository import IndexRow

TODAY = date(2026, 9, 29)
TIERS = {"anonymous": 0, "user": 1, "premium": 2}


class _SameVector:
    def embed_query(self, query):
        return np.array([1.0, 0.0], dtype=np.float32)


def _row(title, tier="anonymous", effective_from=None, effective_to=None):
    return IndexRow(uuid.uuid4(), uuid.uuid4(), 0, f"Chính sách nghỉ phép ({title})", [1.0, 0.0], {}, title, {}, None,
                    "general", 1.0, tier, effective_from, effective_to)


SNAPSHOT = KnowledgeSnapshot.build(
    [
        _row("public"),
        _row("members", tier="user"),
        _row("premium", tier="premium"),
        _row("expired", effective_to=date(2026, 9, 28)),
        _row("future", effective_from=date(2026, 10, 1)),
        _row("in force", effective_from=date(2026, 9, 29), effective_to=date(2026, 9, 29)),
        _row("typo tier", tier="usr"),
    ],
    version=1,
    tier_level=lambda tier: TIERS.get(tier, 0),
)


def _titles(access_level):
    results = ContextRetriever(_SameVector()).search(
        "chính sách nghỉ phép", SNAPSHOT, top_k=10, semantic_weight=1.0, threshold=0.0, semantic_threshold=0.0,
        max_context_chunks=10, expansion_radius=0, access_level=access_level, today=TODAY,
    )
    return {item.chunk.document_title for item in results}


@pytest.mark.hard_gate
def test_anonymous_visitors_see_only_public_documents_in_force():
    assert _titles(0) == {"public", "in force"}


@pytest.mark.hard_gate
def test_signed_in_tiers_see_their_level_and_below_but_never_expired_future_or_unknown_tiers():
    assert _titles(1) == {"public", "in force", "members"}
    assert _titles(2) == {"public", "in force", "members", "premium"}
