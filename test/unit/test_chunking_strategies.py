"""Chunking strategies split extracted text as an admin chose (no network, no database)."""

import pytest

from core.document_processing.chunking import Chunker, InvalidChunkingError, MAX_CHUNK_CHARS
from core.document_processing.chunking.chunker import section_label
from core.document_processing.chunking.heading_strategy import HeadingChunker
from core.document_processing.chunking.legal_article_strategy import LegalArticleChunker
from core.document_processing.chunking.qa_pair_strategy import QaPairChunker
from core.document_processing.chunking.table_rows_strategy import TableRowsChunker
from models.knowledge import ChunkingSpec

LAW = """LUẬT NGƯỜI LAO ĐỘNG VIỆT NAM ĐI LÀM VIỆC Ở NƯỚC NGOÀI THEO HỢP ĐỒNG
Căn cứ Hiến pháp nước Cộng hòa xã hội chủ nghĩa Việt Nam;

## Chương I
QUY ĐỊNH CHUNG

**Điều 1. Phạm vi điều chỉnh**
Luật này quy định về hoạt động đưa người lao động Việt Nam đi làm việc ở nước ngoài.

Điều 2. Đối tượng áp dụng
1. Người lao động Việt Nam đi làm việc ở nước ngoài theo hợp đồng.
2. Doanh nghiệp hoạt động dịch vụ đưa người lao động đi làm việc ở nước ngoài.

Chương II
QUYỀN VÀ NGHĨA VỤ

Dieu 6. Quyen cua nguoi lao dong
Người lao động được cung cấp thông tin về chính sách, pháp luật.
"""


def test_legal_article_labels_each_article_and_prefixes_its_chapter():
    drafts = LegalArticleChunker().split(LAW)

    articles = [d for d in drafts if "article" in d.metadata]
    assert [d.metadata["article"] for d in articles] == ["Điều 1", "Điều 2", "Điều 6"]
    assert articles[0].metadata["chapter"] == "Chương I"
    assert articles[2].metadata["chapter"] == "Chương II"  # accent-less markers are recognised too
    # The short "Chương I / QUY ĐỊNH CHUNG" header is not its own chunk; it titles the articles.
    assert articles[0].content.startswith("Chương I QUY ĐỊNH CHUNG\n")
    assert not any(d.content.startswith("## Chương") for d in drafts)
    # Text before the first marker is kept, without structural metadata.
    assert drafts[0].metadata == {} and "Căn cứ Hiến pháp" in drafts[0].content


def test_legal_article_can_split_at_clauses():
    drafts = LegalArticleChunker(split_at="clause").split(LAW)

    clauses = [d.metadata for d in drafts if "clause" in d.metadata]
    assert clauses == [
        {"chapter": "Chương I", "article": "Điều 2", "clause": "Khoản 1"},
        {"chapter": "Chương I", "article": "Điều 2", "clause": "Khoản 2"},
    ]


def test_oversized_article_is_size_split_and_keeps_its_labels():
    long_article = "Điều 9. Hợp đồng\n" + " ".join(f"Câu thứ {i} của điều này rất dài." for i in range(60))
    drafts = LegalArticleChunker(max_chars=300).split(long_article)

    assert len(drafts) > 1
    assert all(d.metadata == {"article": "Điều 9"} for d in drafts)
    assert all(len(d.content) <= 450 for d in drafts)
    assert drafts[1].content.startswith("Điều 9. Hợp đồng\n")  # later pieces repeat the article title


def test_text_without_markers_falls_back_to_size_with_a_warning():
    result = Chunker().split("Một đoạn văn bình thường. " * 10, ChunkingSpec("legal_article", {}), "docling")

    assert result.drafts and all("article" not in d.metadata for d in result.drafts)
    assert any("No Điều markers" in warning for warning in result.warnings)


def test_qa_pairs_from_prefixed_lines_and_tables():
    text = """Câu hỏi 1: Hồ sơ gồm những gì?
Trả lời: Hộ chiếu và hợp đồng.
a. Bản sao có chứng thực.
**Q:** How long is the visa?
**A:** Two years.

| STT | Câu hỏi | Trả lời |
|---|---|---|
| 1 | Phí là bao nhiêu? | Theo quy định. |
| 2 | nan | nan |
"""
    drafts = QaPairChunker().split(text)

    assert [d.metadata["question"] for d in drafts] == [
        "Phí là bao nhiêu?",
        "Hồ sơ gồm những gì?",
        "How long is the visa?",
    ]
    # A lettered list item continues the answer instead of starting a new one.
    assert drafts[1].content == "Hỏi: Hồ sơ gồm những gì?\nĐáp: Hộ chiếu và hợp đồng.\na. Bản sao có chứng thực."


def test_qa_pair_without_pairs_is_rejected():
    with pytest.raises(InvalidChunkingError, match="No question/answer pairs"):
        QaPairChunker().split("Chỉ là một đoạn văn.")


def test_table_rows_repeat_the_header_and_skip_empty_rows():
    rows = "\n".join(f"| {i} | Nghề {i} |" for i in range(1, 6))
    text = f"## Sheet: Jobs\n| STT | Nghề |\n|---|---|\n{rows}\n| nan | nan |\nGhi chú cuối bảng."
    drafts = TableRowsChunker(rows_per_chunk=2).split(text)

    tables = [d for d in drafts if "rows" in d.metadata]
    assert [d.metadata for d in tables] == [
        {"rows": "1-2", "sheet": "Jobs"},
        {"rows": "3-4", "sheet": "Jobs"},
        {"rows": "5-5", "sheet": "Jobs"},
    ]
    assert all(d.content.startswith("| STT | Nghề |\n") for d in tables)
    assert drafts[-1].content == "Ghi chú cuối bảng."


def test_a_heading_right_above_a_table_goes_with_every_table_chunk():
    # A DOCX CV: the section heading must not stay behind at the end of the preceding prose chunk.
    text = (
        "- Có khả năng sử dụng tiếng Anh.\n##### 2 QUÁ TRÌNH ĐÀO TẠO\n\n"
        "| Thời gian | Trường |\n|---|---|\n| 2022 – 2025 | Đại học Swinburne |\n| 2022 | IELTS |"
    )
    drafts = TableRowsChunker(rows_per_chunk=1).split(text)

    assert drafts[0].content == "- Có khả năng sử dụng tiếng Anh."
    tables = drafts[1:]
    assert len(tables) == 2
    assert all(d.content.startswith("##### 2 QUÁ TRÌNH ĐÀO TẠO\n| Thời gian | Trường |") for d in tables)
    assert tables[0].metadata == {"rows": "1-1", "heading": "2 QUÁ TRÌNH ĐÀO TẠO"}


def test_heading_sections_are_capped_by_size():
    text = "# Title\nIntro.\n## Part A\n" + "Một câu. " * 100 + "\n### Detail\nKept with Part A."
    drafts = HeadingChunker(max_level=2, max_chars=200).split(text)

    assert drafts[0].metadata == {"heading": "Title"}
    part_a = [d for d in drafts if d.metadata.get("heading") == "Part A"]
    assert len(part_a) > 1 and "Kept with Part A." in part_a[-1].content


def test_headings_without_text_carry_into_the_next_section():
    # Docling flattens a PDF CV's headings to "##": name, section and job title arrive with nothing under them.
    text = "## LUONG CHI DUC\n## WORK EXPERIENCE\n## AI Engineer\n## Tri Nghia Tech\n- Led teams of 5-6.\n## EDUCATION\n"
    drafts = HeadingChunker(max_level=6, max_chars=None).split(text)

    assert len(drafts) == 2
    assert drafts[0].content.startswith("## LUONG CHI DUC") and "Led teams" in drafts[0].content
    assert drafts[0].metadata == {"heading": "Tri Nghia Tech"}
    assert drafts[1].content == "## EDUCATION"  # a trailing lone heading is kept, not dropped


def test_upload_and_rechunk_auto_split_docling_markdown_the_same_way():
    # Uploads chunk inside the Docling processor; re-chunk "auto" uses the Chunker. They must agree.
    from core.document_processing.docling_processor import DoclingProcessor

    text = "## LUONG CHI DUC\n## WORK EXPERIENCE\n## Tri Nghia Tech\n- Led teams.\n## EDUCATION\nSwinburne"
    uploaded = DoclingProcessor()._chunk_markdown_by_headings(text)

    assert uploaded == [d.content for d in Chunker().split(text, ChunkingSpec(), "docling").drafts]
    assert uploaded[0].startswith("## LUONG CHI DUC") and "Led teams." in uploaded[0]


def test_auto_follows_the_extraction_path():
    text = "# A\n" + "x " * 700 + "\n# B\nshort"
    chunker = Chunker()

    by_heading = chunker.split(text, ChunkingSpec(), "docling").drafts
    by_size = chunker.split(text, ChunkingSpec(), "ocr").drafts

    assert [d.content.splitlines()[0] for d in by_heading] == ["# A", "# B"]  # unbounded, like Docling today
    assert len(by_size) != len(by_heading)


def test_whole_rejects_text_longer_than_one_chunk():
    with pytest.raises(InvalidChunkingError, match="at most"):
        Chunker().split("x" * (MAX_CHUNK_CHARS + 1), ChunkingSpec("whole", {}), "text")


@pytest.mark.parametrize(
    "spec",
    [ChunkingSpec("nonsense", {}), ChunkingSpec("size", {"max_chars": 500, "unknown": 1})],
)
def test_unknown_strategy_or_parameter_is_rejected(spec):
    with pytest.raises(InvalidChunkingError):
        Chunker().split("text", spec, "text")


def test_spec_round_trips_through_its_stored_form():
    spec = ChunkingSpec("legal_article", {"split_at": "clause"})

    assert ChunkingSpec.from_json(spec.to_json()) == spec
    assert ChunkingSpec.from_json({}) == ChunkingSpec()


def test_section_label_for_citations():
    articles = [d for d in LegalArticleChunker().split(LAW) if "article" in d.metadata]
    assert section_label(articles[2].metadata) == "Chương II · Điều 6"
    assert section_label({"heading": "Quên mật khẩu"}) == "Quên mật khẩu"
    assert section_label({"url": "https://x"}) is None
