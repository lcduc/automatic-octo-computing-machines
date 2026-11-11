# Docs

Repository-wide documentation. Anything about one folder lives in that folder's `README.md`.
File names are lowercase kebab-case.

| Path | What it is | Kept current? |
|---|---|---|
| [checklists/](checklists/README.md) | Definition of done by aspect: product (`production.md`), code quality, testing, app security, privacy, CI/supply chain, optimization | Yes, update marks in the same change |
| [api.md](api.md) | API reference (public chat + admin) | Yes |
| [openapi.json](openapi.json) | Machine-readable twin of `api.md`; regenerate with `python -m scripts.export_openapi` from `backend/` | Yes (CQ-16) |
| [chatbot-routing-spec.md](chatbot-routing-spec.md) | Spec of the chat pipeline: intent routing, RAG, tool execution, handoff, refusal, injection defense | Yes |
| [deployment.md](deployment.md) | Deployment, embedding, backups and operations for a client box | Describes the handed-over VPS setup; not maintained here |
| [performance.md](performance.md) | Load test of the chat pipeline: latency, ceiling, VRAM | Point-in-time (2026-10-24) |
| [privacy-data-flows.md](privacy-data-flows.md) | Map of personal data flows (PRV-01) | Yes |
| [diagrams/](diagrams/) | Architecture, chat-answer and ingestion diagrams (SVG + HTML) | Yes |
| [reports/](reports/) | Dated reviews and experiment write-ups | No, point-in-time |
