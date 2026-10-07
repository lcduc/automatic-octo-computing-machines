"""The bundle format rejects files an import must not trust."""

import pytest
from pydantic import ValidationError

from models.knowledge_bundle import KnowledgeBundle

DOCUMENT = {
    "source": "FAQ",
    "title": "Doc",
    "file_type": "text",
    "content_hash": "abc",
    "chunks": [{"content": "hello"}],
}


def test_a_minimal_bundle_is_valid():
    bundle = KnowledgeBundle.model_validate({"version": 1, "documents": [DOCUMENT]})

    assert bundle.documents[0].access_tier == "anonymous" and bundle.documents[0].chunks[0].edited is False


@pytest.mark.parametrize(
    "broken",
    [
        {"version": 2, "documents": [DOCUMENT]},
        {"version": 1, "documents": [{**DOCUMENT, "chunks": []}]},
        {"version": 1, "documents": [{**DOCUMENT, "chunks": [{"content": ""}]}]},
        {"version": 1, "documents": [{**DOCUMENT, "source": "bad name!"}]},
        {"version": 1, "documents": [{**DOCUMENT, "content_hash": ""}]},
    ],
)
def test_invalid_bundles_are_rejected(broken):
    with pytest.raises(ValidationError):
        KnowledgeBundle.model_validate(broken)
