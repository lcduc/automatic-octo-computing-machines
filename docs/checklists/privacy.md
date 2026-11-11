# Privacy checklist (engineering)

How the code and build handle personal data. The legal side (Law 91/2025/QH15, consent, LLM
provider retention, cross-border transfer) is in [production.md](production.md) §14 and §16, and
the data map is [privacy-data-flows.md](../privacy-data-flows.md); this file does not repeat them.

Last assessed: 2026-11-10 at `2c55f4e`.

## Builds and repository

- [ ] PRIV-01 Images never contain local runtime data — `backend/.dockerignore` excludes only `data/chunks`, `data/vectors` and `data/temp`, so a local `docker build backend` copies `backend/data/uploads/` (uploaded documents) and `backend/data/logs/` into the image. CI and release builds start from a clean checkout and are not affected. Fix: exclude `data/` entirely (the Dockerfile recreates the directories)
- [x] PRIV-02 Runtime data never committed — `data/`, `logs/`, `.env` gitignored (`.gitignore`)

## Runtime

- [x] PRIV-03 Client IPs stored only as hashes in rate-limit keys — `hashed(...)` in `middleware/ip_rate_limit_middleware.py`, `api/v1/routes/admin/auth.py`
- [x] PRIV-04 Contact details masked in admin views; secrets redacted in the audit log — `mask_email`/`mask_phone` in `services/handoff_service.py`, `REDACTED` in `services/audit_service.py`
- [~] PRIV-05 Logs carry no message content — no logger call in the chat path logs the question or answer text (checked by grep), but nothing enforces it; `docling_processor.py:241` logs OCR error text, which can contain document content
- [x] PRIV-06 Data-subject export and delete, and scheduled retention purge (PRV-03, PRV-04) — `services/privacy_service.py`, `core/storage/retention_repository.py`

## Tests

- [x] PRIV-07 Privacy paths tested — `test/integration/test_privacy_api.py` (export/delete) and `test/integration/test_retention.py` (purge); `privacy_service.py` 80%, `privacy_repository.py` 79% line coverage (see [testing.md](testing.md) TST-06)
- [x] PRIV-08 Test and demo data contain no real personal data — the only contact details in `backend/scripts/demo_data/` are `demo.visitor@example.com`, `demo.visitor2@example.com` and `0900000001`
