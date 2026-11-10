# Checklists

What "done" means for this repository, split by aspect. Each checklist is short and holds the
criteria once; when an item fails inside one folder, that folder's `README.md` lists it under
**Status** with the same ID, so a developer or agent working in the folder sees it there.

| Checklist | IDs | Covers | `[x]` / items |
|---|---|---|---|
| [production.md](production.md) | `CAP` `RES` `ARC` … `POST` | The product's definition of done: architecture, identity, ingestion, retrieval, generation, admin, observability, retention, OWASP LLM security (§15), Vietnam privacy (§16), evaluation, operations | 131 / 204 |
| [code-quality.md](code-quality.md) | `CQ` | Layering, file size, linting, typing, error handling, dead code, repository docs | 8 / 18 |
| [testing.md](testing.md) | `TST` | What CI runs, coverage, untested critical paths, flaky tests, frontend tests | 5 / 12 |
| [security.md](security.md) | `APPSEC` | Web/API security of the code and containers (auth, sessions, limits, headers, secrets, SSRF/SQLi) | 12 / 15 |
| [privacy.md](privacy.md) | `PRIV` | Engineering-side handling of personal data (builds, logs, masking, deletion) | 6 / 8 |
| [ci-supply-chain.md](ci-supply-chain.md) | `SUP` | Pinning, audits, Dependabot, required checks, workflow permissions, images, licence | 5 / 15 |
| [optimization.md](optimization.md) | `OPT` | Chat-path throughput, VRAM, image and build size, CI time, frontend bundles | 4 / 13 |

## Conventions

- `[x]` done, `[~]` partial, `[ ]` todo, `[-]` intentionally skipped (reason given).
- Every mark cites its evidence: a file, test, workflow, measurement or doc. A mark without
  evidence is a guess; change it to `[ ]` or add the evidence.
- IDs never change or get reused; reference them in commits and PRs (`fix(widget): SUP-04`).
- When you change a mark, update the count in the table above, and when you close an item,
  remove its line from the folder README's Status section, in the same change.
- The aspect checklists were assessed on 2026-11-10 at `2c55f4e`; each file says when it was last
  re-assessed.
