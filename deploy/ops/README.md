# `deploy/ops/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
The ops CLI for one client box: `install`, `preflight`, `deploy`, `rollback`, `backup`, `backups`, `restore`,
`rotate-secrets`. Standard library only, so it runs from its own small image (`chatbot-ops`, invoked as
`chatbot <command>` by the wrapper `install.sh` writes) or from a checkout as `python -m deploy.ops`. It
drives `docker compose`, `rclone` and `openssl` through one `CommandRunner` seam. Backend code (API,
`scripts.manage`) does not belong here; the ops CLI calls it inside a one-off API container when it needs it.
VPS operations are out of scope now; this README documents the code.

## Files

| File | Public names | What it does |
|---|---|---|
| `__init__.py` | — | Package docstring only. |
| `__main__.py` | `OpsCli`, `main` | Argument parsing and command dispatch. Install dir from `--dir` / `OPS_DIR` (default `/opt/chatbot`); templates from `OPS_TEMPLATES_DIR` (image) or the checkout root. |
| `context.py` | `OpsContext` | Builds the collaborators (layout, env files, runner, compose, backup, alert …) for one install directory from its current settings. |
| `layout.py` | `InstallLayout`, `copy_templates` | Paths inside an install dir (`.env`, `ops.env`, `secrets/`, `handover/`, `.deploy_history`); copies the release's `docker-compose.yml`, `deploy/Caddyfile`, `deploy/postgres/10-app-role.sh` and the DBA grants template into it (skipped when installing into the checkout). |
| `answers.py` | `AnswersError`, `BackupAnswers`, `AlertAnswers`, `HostAuthAnswers`, `BusinessDbAnswers`, `InstallAnswers`, `AnswersFile` | The per-client answers (TOML file or prompts), validated before anything is written; see `../answers.example.toml`. |
| `prompter.py` | `InteractivePrompter` | Interactive questions when no answers file is given; on a rerun offers current values and keeps secrets on Enter. |
| `env_file.py` | `EnvFileError`, `EnvFile` | Reads/writes `.env` / `ops.env` (mode 0600) in the subset compose, Docker `env_file` and python-dotenv parse identically. |
| `secret_generator.py` | `SecretGenerator` | Generates every secret an install needs; reruns keep existing values. |
| `host_bundle.py` | `HostIntegrationBundle` | Generates the host-site RS256 key pair (openssl) and `handover/host-integration.zip`: the `host-sdk/` files with issuer, audience and domains filled in, plus the private key. |
| `installer.py` | `InstallError`, `Installer` | `chatbot install`: copy templates → answers → write settings → generate secrets → pull + preflight → deploy → bootstrap the first owner (`scripts.manage bootstrap-admin`) → security self-check. |
| `preflight.py` | `Preflight` | `chatbot preflight`: GPU (through the API image), RAM, disk, DNS for both domains, backup target writable, alert channel delivers; `--after-deploy` adds the security self-check. |
| `security_check.py` | `SecuritySelfCheck` | On the running stack: only Caddy publishes 80/443, internal services on the internal network, security headers on both domains, no non-admin API route reachable, no missing/short/example secret. |
| `https_probe.py` | `ProbeResponse`, `ProbeError`, `HttpsProbe` | HTTPS to `127.0.0.1:443` with the real domain as SNI/Host, so certificates are verified without hairpin NAT. |
| `deployer.py` | `DeployError`, `DeployResult`, `Deployer` | `deploy <tag>`: pull, back up, ensure the app DB role, start the stack (`migrate` runs Alembic first), wait for health (up to 900 s), append to `.deploy_history`; `rollback` redeploys the previous entry. |
| `compose.py` | `Compose` | `docker compose` for the install dir's stack (project `chatbot`), incl. health polling. |
| `backup.py` | `BackupError`, `BackupSet`, `BackupManager` | `pg_dump` + uploads tarball, shipped off-server with rclone, pruned by `keep_days`; 3 kept locally; `restore` of a named or the newest set. |
| `backup_target.py` | `BackupTargetError`, `BackupTarget` | Turns `BACKUP_TARGET` (`s3://…`, `sftp://…`, `/path`) into an rclone remote via `RCLONE_CONFIG_*` env vars; no rclone config file is written. |
| `rotation.py` | `SecretRotator` | `rotate-secrets`: changes DB passwords inside PostgreSQL first, then files, then recreates the stack; `--include-visitor-cookie` also rotates the visitor-cookie secret. |
| `operator_alert.py` | `OperatorAlert` | Sends ops alerts (e.g. a failed nightly backup) via `scripts.manage send-alert` in a one-off API container, so ops and backend share one alert config. |
| `check_result.py` | `CheckResult`, `report` | One preflight/security check outcome and the one-line-per-check report. |
| `runner.py` | `CommandError`, `CommandResult`, `CommandRunner`, `merged_env` | The single `subprocess` seam; tests swap in a fake runner. |
| `Dockerfile` | — | `chatbot-ops` image: `docker:27-cli` + python3, openssl, tzdata and rclone 1.71; copies the CLI and the compose/deploy/host-sdk templates; entrypoint `python3 -m deploy.ops`. Build context is the repo root. |
| `Dockerfile.dockerignore` | — | Allow-list build context for that image (BuildKit reads it instead of the root `.dockerignore`). |

### `tests/`
Run in CI job `ops` (`.github/workflows/ci.yml`), which installs only pytest because the CLI is stdlib-only.
No Docker daemon is needed: commands go through fake runners.

| File | Public names | What it covers |
|---|---|---|
| `test_ops_deploy.py` | `FakeRunner`, `FakeProbe`, `test_*` | Deploy records history and ensures the app role; failed deploy explains rollback; backup ships dump + uploads and prunes; failed backup alerts; preflight reports each failing prerequisite; security self-check passes a correct stack and catches leaks. |
| `test_ops_host_bundle.py` | `FakeOpenssl`, `test_key_pair_is_generated_once_and_the_bundle_is_filled_in` | Key pair generated once (CRLF normalised), bundle placeholders filled. Reads `host-sdk/` from the repo root. |
| `test_ops_settings.py` | `test_*` | `.env` quoting round trip, answers validation and mapping, sector warnings, backup targets → rclone remotes, secret generation and rotation. |

## Dependencies
- Python standard library only (no third-party imports; the image has no pip packages).
- External tools at run time: Docker CLI with Compose, rclone, openssl; the API image (for GPU checks,
  `scripts.manage bootstrap-admin` / `send-alert`).
- Reads templates: `docker-compose.yml`, `deploy/Caddyfile`, `deploy/postgres/`, `deploy/business_db/reader_grants.sql`,
  `host-sdk/`.
- Used by: `deploy/install.sh` (the `chatbot` wrapper), `.github/workflows/release.yml` (builds the image),
  local dev (`python -m deploy.ops install --dir . --answers deploy/answers.example.toml --skip-deploy`).

## Run / test
From the repo root:

```bash
python -m deploy.ops --help
python -m pytest deploy/ops/tests
docker build -f deploy/ops/Dockerfile -t chatbot-ops .
```

## Known problems and history
- Built on 2026-09-28/29: answers, settings and secrets (c0f2215); deploy, rollback, backup, restore and
  rotation (7028f1c); preflight and security self-check (3ba2c79); installer and CLI entry point (4ff992c);
  image and `install.sh` (d02af7e); host signing key and hand-over bundle (befd8e2); model-server health gate
  (81613f9); business-DB answer and read-only preflight (2b3af4a); backup-failure alert (bdc559c); sector
  question with a retention warning for regulated sectors (58c032e, RET-R6).
- openssl on Windows builds emits CRLF PEMs → `host_bundle.py` normalises line endings (`_normalise_pem`).
- The tests lived in `test/unit/` with the backend suite; they moved here with their own CI job in
  `lcduc/automatic-octo-computing-machines#76` (55daf18, 2026-11-10), since the CLI has none of the backend's
  dependencies.
- `host-sdk/README.md` is in `SDK_FILES`, so it ships verbatim (placeholders filled) in the client hand-over zip.

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none recorded.
- Ceilings (`# ceiling:` markers in this folder): none.
