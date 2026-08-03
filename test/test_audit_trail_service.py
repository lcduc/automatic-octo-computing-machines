"""Unit tests for AuditTrailService - the durable per-turn chat log."""

import json
import os

from core.infrastructure.audit.audit_trail_service import AuditTrailService
from models.audit_entry import AuditEntry


def _make_entry(**overrides) -> AuditEntry:
    fields = {
        "query_id": "abc12345",
        "query": "Chính sách nghỉ phép là gì?",
        "rewritten_query": None,
        "response": "<div>Nhân viên được nghỉ 12 ngày mỗi năm.</div>",
        "confidence_score": 0.82,
        "confidence_level": "High",
        "source_count": 3,
        "cached": False,
        "latency_ms": 452.1,
        "success": True,
        "error": None,
    }
    fields.update(overrides)
    return AuditEntry(**fields)


def test_record_appends_one_json_line(tmp_path):
    log_path = tmp_path / "nested" / "audit_trail.jsonl"
    service = AuditTrailService(log_path=str(log_path))

    service.record(_make_entry())
    service.record(_make_entry(query="second question"))

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["query"] == "Chính sách nghỉ phép là gì?"
    assert first["confidence_score"] == 0.82
    assert first["success"] is True

    second = json.loads(lines[1])
    assert second["query"] == "second question"


def test_record_creates_missing_parent_directory(tmp_path):
    log_path = tmp_path / "does" / "not" / "exist" / "audit_trail.jsonl"
    service = AuditTrailService(log_path=str(log_path))

    service.record(_make_entry())

    assert os.path.exists(log_path)


def test_record_swallows_write_failures(tmp_path):
    # Point the log path at a directory instead of a file: opening it for
    # append will raise, which record() must catch rather than propagate.
    log_dir = tmp_path / "a_directory"
    log_dir.mkdir()
    service = AuditTrailService(log_path=str(log_dir))

    service.record(_make_entry())  # must not raise
