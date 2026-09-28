"""Local fallback extractors return their usual chunks plus the full text kept for re-chunking."""

import asyncio

from core.document_processing.extractors import CSVTextExtractor, TXTTextExtractor, smart_chunk_text


def test_text_extraction_keeps_the_chunks_and_returns_the_whole_text():
    text = "Câu một. " * 300
    extraction = asyncio.run(TXTTextExtractor().extract(text.encode("utf-8"), "notes.txt"))

    assert extraction.text == text
    assert extraction.chunks == smart_chunk_text(text, 1000, 200)
    assert len(extraction.chunks) > 1


def test_csv_text_is_a_markdown_table_and_chunks_keep_their_old_format():
    content = "Nghề,Lương\nHàn,1000\n,\nĐiện,1200\n".encode("utf-8")
    extraction = asyncio.run(CSVTextExtractor().extract(content, "jobs.csv"))

    assert extraction.text.splitlines() == [
        "| Nghề | Lương |",
        "|---|---|",
        "| Hàn | 1000.0 |",
        "| nan | nan |",
        "| Điện | 1200.0 |",
    ]
    # The empty row still splits the fallback chunks, as before.
    assert extraction.chunks == ["Columns: Nghề | Lương\nHàn | 1000.0", "Columns: Nghề | Lương\nĐiện | 1200.0"]
