"""PDFs with a usable text layer skip OCR; empty or gibberish ones go to the OCR engine (no model weights)."""

import pymupdf

from core.document_processing import docling_processor
from core.document_processing.docling_processor import DoclingProcessor
from utils.text_utils import TextUtils


def _write_pdf(tmp_path, text):
    path = tmp_path / "doc.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
        document.save(str(path))
    return path


def test_pdf_with_real_text_skips_ocr(tmp_path, monkeypatch):
    monkeypatch.delenv("OCR_FORCE_ALL_PDFS", raising=False)
    path = _write_pdf(tmp_path, "Quarterly revenue grew twelve percent year over year.")
    assert DoclingProcessor()._pdf_needs_ocr(path) is False


def test_pdf_without_text_goes_to_ocr(tmp_path, monkeypatch):
    monkeypatch.delenv("OCR_FORCE_ALL_PDFS", raising=False)
    assert DoclingProcessor()._pdf_needs_ocr(_write_pdf(tmp_path, "")) is True


def test_broken_font_encoding_text_is_gibberish():
    assert TextUtils.needs_ocr_fallback("��  ab")


def test_short_lines_are_not_gibberish():
    assert not TextUtils.needs_ocr_fallback("Số\nKý\n" * 20)


def test_docling_converter_has_its_own_ocr_off(monkeypatch):
    captured = {}
    monkeypatch.setattr(docling_processor, "DocumentConverter", lambda format_options: captured.update(format_options))

    DoclingProcessor._build_converter()

    assert captured[docling_processor.InputFormat.PDF].pipeline_options.do_ocr is False
