# CI and supply-chain checklist

Can a dependency, a workflow or an image bring in something nobody reviewed? Security of the code
itself is in [security.md](security.md).

Last assessed: 2026-11-10 at `2c55f4e`.

## Dependencies

- [x] SUP-01 Python dependencies pinned exactly — `backend/requirements.txt`, torch/torchvision in `backend/requirements-torch.txt`, paddlepaddle in `backend/Dockerfile`
- [x] SUP-02 npm dependencies locked and installed with `npm ci` — `frontends/*/package-lock.json`, `ci.yml`, both Dockerfiles
- [x] SUP-03 Python dependencies audited on every PR with no ignored advisories — job `Dependency audit (pip-audit, npm audit)`, `--strict`, ignore list cleared 2026-11-10. Advisory only (`continue-on-error`), so a new CVE never blocks an unrelated PR
- [x] SUP-04 npm dependencies audited — `npm audit --omit=dev` for the widget and admin web in the same advisory job (reads `package-lock.json` only). The widget's `next@16.3.6` critical batch and the `sharp`/`source-map-js` highs were fixed on 2026-11-11 (`next` 16.4.6); production dependencies of both frontends audit clean. Dev tooling still has moderate advisories (`vitest` 5.0.2, `minimatch` via `typescript-eslint`), outside this audit's scope
- [x] SUP-05 Dependabot covers every ecosystem — `.github/dependabot.yml`: pip (backend, streamlit, CI tools in `.github/requirements-ci.txt`), npm (widget, admin), docker (backend, widget, admin, ops images) and GitHub Actions; majors are ignored everywhere and done by hand, and the `python` base image stays on 3.11. Dependabot's Dockerfile parser only matches `FROM` at the start of a line, so `backend/Dockerfile` was de-indented
- [ ] SUP-06 Dependabot security alerts and updates on — "Dependabot security updates" is disabled in the repository settings

## Workflows

- [x] SUP-07 CI tools pinned — `ruff`, `pytest` (ops job) and `pip-audit` install with `-c .github/requirements-ci.txt`, which Dependabot bumps
- [x] SUP-08 Workflows least-privilege — every workflow declares `permissions:` (`contents: read`; `release.yml` adds `packages: write`), and every action is pinned to a commit SHA with its version in a comment (`@<sha> # v7.0.1`), which Dependabot keeps current
- [~] SUP-09 Every CI job is a required check — the `main` ruleset requires one approving review plus `Lint (ruff)` and `Tests (pytest)`; the widget, admin web and ops CLI jobs can fail and still merge
- [x] SUP-10 `main` protected — ruleset blocks deletion and force-push and requires a pull request with one approval

## Images

- [x] SUP-11 Image builds verified on `main` — `docker-build.yml` (about 25 min with the GitHub Actions layer cache); release images are tagged per version in GHCR (`release.yml`)
- [ ] SUP-12 Images scanned for vulnerabilities — no Trivy/Grype step (also SEC-09 in [production.md](production.md))
- [~] SUP-13 Base images pinned — `python:3.11-slim`, `node:24-alpine` and `caddy:2-alpine` are floating tags, not digests; compose pins `caddy:2.10` and `pgvector/pgvector:pg17`
- [ ] SUP-14 Release images carry an SBOM and a signature — `release.yml` pushes plain tags; no `sbom:` or cosign step

## Licence

- [ ] SUP-15 Licence matches how the code is distributed — `LICENSE` is MIT and the repository is public, while [production.md](production.md) §0 describes a closed-source product shipped to clients. Decide which is true; if closed, the repository should be private and the licence proprietary
