"""
The real upload path: ``MainDocumentProcessor`` with real Docling and the real local extractors.

Every other test injects a fake processor, so without these nothing exercised the parsers an
upload actually goes through (TST-07). No database and no network: DOCX, XLSX, CSV and Markdown
convert in Docling without model weights. Only Docling's PDF layout model is a download (baked
into the image by ``scripts/download_models.py``), so the one test that needs it is skipped when it
is neither baked nor cached; the PDF fallback is tested regardless.
"""

import io
from typing import Dict

import docx
import openpyxl
import pymupdf
import pytest
from huggingface_hub import scan_cache_dir

from app.core.document_processing.docling_processor import DoclingProcessor, docling_models_dir
from app.core.document_processing.main_processor import MainDocumentProcessor
from app.models.knowledge import EXTRACTION_DOCLING, EXTRACTION_LOCAL

PDF_SENTENCE = "Warranty policy: products are covered for twelve months."
#: Substring of the Hugging Face repo id of Docling's PDF layout model.
DOCLING_LAYOUT_REPO = "docling-layout"


def docling_layout_model_cached() -> bool:
    """Whether Docling's PDF layout model is baked into ``MODELS_DIR`` or in the Hugging Face cache."""
    if docling_models_dir().is_dir():
        return True
    try:
        return any(DOCLING_LAYOUT_REPO in repo.repo_id for repo in scan_cache_dir().repos)
    except Exception:
        # No cache directory yet counts as "not cached".
        return False


def docx_bytes() -> bytes:
    """A Vietnamese Word document with two headings and a table."""
    document = docx.Document()
    document.add_heading("Chính sách bảo hành", level=1)
    document.add_paragraph("Sản phẩm được bảo hành 12 tháng kể từ ngày mua.")
    document.add_heading("Đổi trả", level=2)
    document.add_paragraph("Khách hàng được đổi trả trong vòng 7 ngày.")
    table = document.add_table(rows=2, cols=2)
    for (row, col), value in {(0, 0): "Gói", (0, 1): "Giá", (1, 0): "Cơ bản", (1, 1): "100.000 đ"}.items():
        table.cell(row, col).text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def xlsx_bytes() -> bytes:
    """A one-sheet price list."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Bảng giá"
    sheet.append(["Gói", "Giá"])
    sheet.append(["Cơ bản", 100000])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def pdf_bytes() -> bytes:
    """A one-page PDF with a real text layer (so it never goes to OCR)."""
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), PDF_SENTENCE)
        return document.tobytes()


@pytest.fixture(scope="module")
def processor() -> MainDocumentProcessor:
    """One processor for the module: Docling's converter is built once and reused, as in the worker."""
    return MainDocumentProcessor()


@pytest.fixture(autouse=True)
def no_forced_ocr(monkeypatch) -> None:
    """A developer's ``OCR_FORCE_ALL_PDFS`` must not send the text-layer PDF to OCR."""
    monkeypatch.delenv("OCR_FORCE_ALL_PDFS", raising=False)


@pytest.mark.asyncio
async def test_docx_is_converted_by_docling_with_headings_and_tables(processor) -> None:
    result = await processor.process_file(docx_bytes(), "bao-hanh.docx")

    assert result["extraction_method"] == EXTRACTION_DOCLING
    assert result["documents"][0].startswith("## Chính sách bảo hành")
    assert any("Đổi trả" in chunk for chunk in result["documents"])
    assert "Cơ bản" in result["text"] and "100.000 đ" in result["text"]
    assert result["metadata"]["file_type"] == ".docx"
    assert result["metadata"]["total_chunks"] == len(result["documents"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("bang-gia.xlsx", xlsx_bytes(), "Cơ bản"),
        ("bang-gia.csv", "Gói,Giá\nCơ bản,100000\n".encode("utf-8"), "Cơ bản"),
        ("gioi-thieu.md", "# Giới thiệu\n\nTrung tâm mở cửa từ 8 giờ.\n".encode("utf-8"), "Trung tâm mở cửa"),
    ],
)
async def test_spreadsheets_and_markdown_are_converted_by_docling(
    processor, filename: str, content: bytes, expected: str
) -> None:
    result = await processor.process_file(content, filename)

    assert result["extraction_method"] == EXTRACTION_DOCLING
    assert any(expected in chunk for chunk in result["documents"])


@pytest.mark.asyncio
async def test_txt_is_read_by_the_local_processor(processor) -> None:
    """Docling does not accept ``.txt``; the local processor must."""
    result = await processor.process_file("Trung tâm mở cửa từ 8 giờ sáng.".encode("utf-8"), "gio-mo-cua.txt")

    assert result["extraction_method"] == EXTRACTION_LOCAL
    assert result["metadata"]["processor_version"] == "TextProcessor"
    assert result["documents"] == ["Trung tâm mở cửa từ 8 giờ sáng."]


@pytest.mark.asyncio
async def test_pdf_falls_back_to_its_text_layer_when_docling_fails(processor, monkeypatch) -> None:
    """A Docling error (e.g. its layout model cannot be fetched) degrades to pypdf instead of failing the upload."""

    async def docling_down(self, content: bytes, filename: str) -> Dict:
        raise RuntimeError("layout model unavailable")

    monkeypatch.setattr(DoclingProcessor, "process_document", docling_down)

    result = await processor.process_file(pdf_bytes(), "bao-hanh.pdf")

    assert result["extraction_method"] == EXTRACTION_LOCAL
    assert result["metadata"]["processor_version"] == "PDFProcessor"
    assert PDF_SENTENCE in result["text"]


@pytest.mark.asyncio
@pytest.mark.skipif(not docling_layout_model_cached(), reason="Docling's PDF layout model is not cached")
async def test_pdf_with_a_text_layer_is_converted_by_docling(processor) -> None:
    result = await processor.process_file(pdf_bytes(), "bao-hanh.pdf")

    assert result["extraction_method"] == EXTRACTION_DOCLING
    assert PDF_SENTENCE in result["text"]


@pytest.mark.asyncio
async def test_document_without_text_is_rejected(processor) -> None:
    empty = io.BytesIO()
    docx.Document().save(empty)

    with pytest.raises(ValueError, match="No content could be extracted"):
        await processor.process_file(empty.getvalue(), "trong.docx")


@pytest.mark.asyncio
async def test_disallowed_extension_is_rejected(processor) -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        await processor.process_file(b"MZ", "setup.exe")
