"""UploadStore keeps queued upload files on disk (no network, no database)."""

import uuid

from core.storage.upload_store import UploadStore


def test_upload_round_trip_leaves_no_partial_file(tmp_path):
    store = UploadStore(str(tmp_path / "uploads"))
    document_id = uuid.uuid4()
    store.save(document_id, "pdf", b"%PDF-1.7")

    assert store.read(document_id, "pdf") == b"%PDF-1.7"
    assert [p.name for p in (tmp_path / "uploads").iterdir()] == [f"{document_id}.pdf"]

    store.delete(document_id, "pdf")
    store.delete(document_id, "pdf")  # already gone: not an error
    assert not store.path_for(document_id, "pdf").exists()
