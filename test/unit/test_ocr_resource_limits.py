"""Parsing/OCR must stay within its CPU budget and never block the API's event loop (no model weights)."""

import sys
import threading
import types

import pytest

from core.document_processing.docling_processor import DoclingProcessor
from core.document_processing.engine_selector import cpu_threads_per_page
from core.document_processing.pp_ocr_engine import PPOCRv6Engine


@pytest.mark.parametrize(
    ("budget", "pages", "expected"),
    [("2", "2", 1), ("6", "2", 3), ("3", "2", 1), ("1", "4", 1), ("4", "0", 4)],
)
def test_cpu_budget_is_split_across_concurrent_pages(monkeypatch, budget, pages, expected):
    monkeypatch.setenv("OCR_CPU_THREADS", budget)
    monkeypatch.setenv("OCR_CONCURRENT_PAGES", pages)
    assert cpu_threads_per_page() == expected


def test_pp_ocr_pipeline_is_built_with_the_thread_cap(monkeypatch):
    captured = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "paddleocr", types.SimpleNamespace(PaddleOCR=FakePaddleOCR))
    PPOCRv6Engine(device="cpu", cpu_threads=3)._get_pipeline()
    assert captured["cpu_threads"] == 3


class _RecordingConverter:
    """Stands in for Docling's converter and records which thread ran it."""

    def __init__(self):
        self.thread_id = None

    def convert(self, path):
        self.thread_id = threading.get_ident()
        document = types.SimpleNamespace(export_to_markdown=lambda: "# Title\n\nBody text")
        return types.SimpleNamespace(document=document)


@pytest.mark.asyncio
async def test_docling_conversion_runs_off_the_event_loop_thread():
    processor = DoclingProcessor()
    converter = _RecordingConverter()
    processor._normal_converter = converter

    result = await processor.process_document(b"# Title\n\nBody text", "notes.md")

    assert result["documents"]
    assert converter.thread_id is not None
    assert converter.thread_id != threading.get_ident()
