# `backend/app/core/document_processing/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Turns an uploaded file (PDF, DOCX, XLSX, CSV, TXT, ...) into extracted text and chunks: Docling
conversion first, OCR for PDFs without a usable text layer, local extractors as the fallback, and
the chunking strategies admins pick per upload. It does not queue uploads, store chunks or embed
them: the ingestion queue and worker live in `services/ingestion_service.py` /
`services/ingestion_worker.py`, re-chunking in `services/chunk_editing_service.py`, persistence in
`core/storage/`, embeddings in `core/retrieval/`.

## Files

| File | Public names | What it does |
|---|---|---|
| `main_processor.py` | `MainDocumentProcessor` | Entry point: validates the extension, routes to Docling, falls back to a local processor only when Docling declines the format (`.txt`) or errors; returns chunks + metadata. |
| `docling_processor.py` | `DoclingProcessor` | Docling conversion to markdown (run in a thread), heading chunking; PDFs with an empty or gibberish text layer are rendered with PyMuPDF and sent page by page to the OCR engine instead. Docling's own OCR is off. |
| `processors.py` | `BaseProcessor`, `TextProcessor`, `PDFProcessor`, `DocumentProcessor`, `SpreadsheetProcessor` | Local fallback processors per format; check file size and delegate to an extractor. |
| `extractors.py` | `Extraction`, `BaseFileExtractor`, `TXTTextExtractor`, `PDFTextExtractor`, `DOCXTextExtractor`, `CSVTextExtractor`, `XLSXTextExtractor`, `extract_tables_from_docx`, `smart_chunk_rows`, `markdown_table`, `smart_chunk_text` | Parse a file once with pypdf / python-docx / pandas / openpyxl; return fallback chunks plus the full text (stored so the document can be re-chunked later). |
| `ocr_base.py` | `OCREngine` | ABC for all OCR engines: `name` and blocking `extract_text(image_path)`; failure returns `""`, never raises. |
| `engine_selector.py` | `get_ocr_engine`, `get_local_engine`, `get_online_engine`, `get_remote_engine`, `cpu_threads_per_page` | Picks the OCR engine for the process (see below); each engine is built once behind a lock and reused. |
| `pp_ocr_engine.py` | `PPOCRv6Engine` | CPU engine: PaddleOCR PP-OCRv6 multilingual pipeline (Vietnamese + English in one model). |
| `paddle_vl_engine.py` | `PaddleOCRVLEngine` | GPU engine: PaddleOCR-VL (~0.9B VLM); keeps only the markdown text. Too slow for CPU. |
| `datalab_surya_engine.py` | `DatalabSuryaEngine` | Online engine: submits a page to Datalab's hosted Surya `/api/v1/ocr` and polls for the result. |
| `remote_ocr_engine.py` | `RemoteOCREngine` | Sends each page to the model-server's resident OCR engine via `ModelServerClient`. |

### `chunking/`
`__init__.py` re-exports `Chunker`, `InvalidChunkingError`, `MAX_CHUNK_CHARS`, `STRATEGY_DESCRIPTIONS`.

| File | Public names | What it does |
|---|---|---|
| `chunker.py` | `Chunker`, `section_label`, `STRATEGIES`, `STRATEGY_DESCRIPTIONS` | Builds the strategy named by a `ChunkingSpec` (`auto` = heading for Docling text, size otherwise), runs it, and returns admin warnings (missing structure, tiny, oversize or duplicate chunks). `section_label` builds the citation label (Chương · Điều or heading). |
| `errors.py` | `InvalidChunkingError`, `MAX_CHUNK_CHARS` | Error for unknown strategy / bad params / nothing to chunk; hard chunk-size limit (20,000 chars). |
| `size_strategy.py` | `SizeChunker` | Whole sentences packed up to a character budget. |
| `heading_strategy.py` | `HeadingChunker` | One chunk per markdown heading section, optionally size-capped. |
| `legal_article_strategy.py` | `LegalArticleChunker`, `LEVELS` | Vietnamese legal texts: one chunk per Chương / Mục / Điều / Khoản with breadcrumb metadata for citation. |
| `qa_pair_strategy.py` | `QaPairChunker` | FAQs: one chunk per question/answer pair (`Hỏi:`/`Đáp:` lines or a Q/A table). |
| `table_rows_strategy.py` | `TableRowsChunker` | Groups of table rows, header row repeated in each chunk; per-sheet headings kept. |
| `whole_strategy.py` | `WholeChunker` | The whole text as a single chunk (short entries). |
| `markdown_tables.py` | `table_cells`, `is_separator_row`, `is_empty_row` | Markdown-table line helpers shared by the table-aware strategies. |

### Flow
```
MainDocumentProcessor.process_file
  -> DoclingProcessor.process_document
       PDF + DOCLING_OCR_ENABLED + no/gibberish text layer (or OCR_FORCE_ALL_PDFS)
         -> render pages (PyMuPDF, longest side <= OCR_MAX_IMAGE_SIDE)
         -> get_ocr_engine().extract_text per page (OCR_CONCURRENT_PAGES at once) -> size chunks
       else -> Docling convert in a thread -> markdown -> heading chunks
  -> Docling error / unsupported format only -> processors.py -> extractors.py
Re-chunking later: Chunker.split(stored text, ChunkingSpec, extraction_method)
```

### OCR engine selection (`engine_selector.get_ocr_engine`)
1. `OCR_PROVIDER=datalab` and `DATALAB_API_KEY` set -> `DatalabSuryaEngine` (no key: warning, fall through).
2. `MODEL_SERVER_URL` set -> `RemoteOCREngine` (the model-server holds the engine).
3. Otherwise the local engine: `PaddleOCRVLEngine(gpu:0)` when paddle is compiled with CUDA and sees a
   device, else `PPOCRv6Engine(cpu)` with `OCR_CPU_THREADS // OCR_CONCURRENT_PAGES` threads per page.
   GPU detection asks paddle, not torch: the two are installed independently in the Dockerfile.

### Lazy paddle imports
`paddle` is imported only inside `_gpu_available()` (wrapped in try/except) and `paddleocr` only inside
each engine's `_get_pipeline()`. Importing this package never loads paddle, so unit tests run without
it; `test_ocr_resource_limits.py` stubs `paddleocr` in `sys.modules`. Keep new paddle imports lazy.
Docling and PyMuPDF imports in `docling_processor.py` are also guarded and fail only when used.

## Dependencies
- May import: `app.config`, `app.models` (`knowledge`, `metadata`), `app.utils.text_utils`, and
  `app.core.infrastructure.model_server_client` (remote OCR). Never `api`, `services` or `middleware`
  (layering rule api -> services -> core -> models/utils, config at the bottom; only main.py imports
  middleware; enforced by `test/unit/test_layering.py`).
- Used by: `services/ingestion_service.py`, `services/chunk_editing_service.py`, `api/container.py`,
  `api/schemas/chunking.py`, `api/schemas/knowledge.py`, `core/agent/knowledge_answerer.py`,
  `core/infrastructure/model_server/model_host.py`, `app/worker.py`.
- Heavy deps: Docling (+ torch), PyMuPDF, pypdf, python-docx, pandas, openpyxl, `paddleocr==3.7.0`
  (requirements.txt), `paddlepaddle==3.2.0` (installed by `backend/Dockerfile`, not requirements.txt),
  Datalab HTTP API (only with `OCR_PROVIDER=datalab`; a cross-border sub-processor, see
  `docs/PRIVACY_DATA_FLOWS.md`), OCR model weights.

## Run / test
From `backend/` with `venv` active:
```
pytest test/unit/test_chunking_strategies.py test/unit/test_extractors_text.py \
       test/unit/test_pdf_ocr_routing.py test/unit/test_ocr_resource_limits.py
```
Integration (needs `TEST_DATABASE_URL` to a pgvector database): `test/integration/test_document_lifecycle.py`,
`test_knowledge_service.py`. Lint from repo root: `ruff check .`.

## Known problems and history
- OCR engines used to live in an `ocr/` subfolder; it was flattened into this folder in `e5adde7`
  (2026-08-13). Docstrings in `docling_processor.py` and the paddle comment in `backend/Dockerfile`
  still point at `core/document_processing/ocr` (stale).
- paddlepaddle 3.3.x breaks CPU text detection (oneDNN/PIR executor, upstream PaddlePaddle/Paddle#77340,
  confirmed by running OCR against this code) -> pinned to 3.2.0; re-verify the bug before bumping past
  3.2.x -> `backend/Dockerfile`.
- Paddle's own index (paddlepaddle.org.cn) returned 502 on 2026-11-10 and failed every Docker build ->
  the CPU wheel `paddlepaddle==3.2.0` now comes from PyPI -> lcduc/automatic-octo-computing-machines#83
  (`3ddd2c5`). The GPU build (`paddlepaddle-gpu`) is published only on Paddle's index, so a GPU OCR image
  still depends on it.
- The shipped image has the CPU paddle build, so OCR runs PP-OCRv6 on the CPU; PaddleOCR-VL needs an
  image built with the `paddlepaddle-gpu` line. Docs corrected in #47.
- PyPDF2 3.0.1 never got the fix for CVE-2023-36464 (infinite-loop DoS) -> swapped to pypdf, same
  `PdfReader` API, in `extractors.py` (`fe1f6d5`, 2026-09-21).
- Ingestion moved out of the API into a separate worker and OCR CPU use was capped (`b13904d`,
  2026-09-28): `cpu_threads_per_page` splits `OCR_CPU_THREADS` across concurrent pages so the total stays
  in budget; Docling's converter is capped to the same thread count.
- PDFs whose text layer is gibberish (broken font encoding) returned junk text -> also sent to OCR via
  `TextUtils.needs_ocr_fallback` (`660c6ce`, 2026-09-30).
- Large page renders -> page images capped at `OCR_MAX_IMAGE_SIDE` on the longest side (`54e5b9a`,
  2026-10-15).
- An empty Docling result deliberately does not fall back to local extractors: for a scanned PDF OCR
  already ran, and the extractors read text layers only, so a retry would hide "no readable text"
  (`main_processor.py` docstring).
- Heading chunking produced text-less heading chunks and split table captions from their rows -> merged
  into the next section / kept together (`7383514`, 2026-09-30).
- Answers cite chapter, article or heading -> `section_label` and legal/heading metadata (`1eb16d9`,
  GEN-03, 2026-09-29). Per-upload strategies with preview and re-chunk added in `31a1867` (2026-09-28).
- `api` and worker use the model-server's OCR when `MODEL_SERVER_URL` is set -> `remote_ocr_engine.py`
  (`caa7e10`, 2026-09-29).
- Datalab's `/api/v1/ocr` is the only endpoint that documents itself as Surya; revisit if Datalab removes
  it (`datalab_surya_engine.py` comment).
- pip-audit flags pypdf 6.21.2 CVEs (fixed in 6.21.4, bump pending).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: fix the stale `core/document_processing/ocr` references; bump pypdf to
  6.21.4; RES-03 (chat load measured while an OCR job runs) is still open (`docs/PERFORMANCE.md`).
- Ceilings (`# ceiling:` markers in this folder):
  - `docling_processor.py:135` — Docling parsing shares the process's torch thread pool — move it to a
    worker process if the cap slows chat.
