# Application security checklist

Web, API and container security of the code in this repository. LLM-specific risks (prompt
injection, excessive agency, unbounded consumption) and product items (MFA, idle timeout, tier
gating) are in [production.md](production.md) §5, §12 and §15 and are not repeated here.
Dependency and image scanning are in [ci-supply-chain.md](ci-supply-chain.md).

Last assessed: 2026-11-10 at `2c55f4e`.

## Authentication and sessions

- [x] APPSEC-01 Admin passwords stored as salted scrypt — `services/auth_service.py:94`
- [x] APPSEC-02 JWTs decoded with a fixed algorithm list (and audience for host tokens) — `auth_service.py:366`, `host_identity_service.py:155`
- [x] APPSEC-03 Admin session cookie is `HttpOnly`, `SameSite=Strict`, `Secure` in production, scoped to the admin path; cookie-authenticated writes need `X-Admin-Request: 1` — `api/v1/routes/admin/auth.py:61`, `api/dependencies.py`
- [x] APPSEC-04 Login throttled per IP and per e-mail — `api/v1/routes/admin/auth.py:47`
- [x] APPSEC-05 API keys hashed, scoped, expiring and revocable, and refused when a request carries browser-only headers — `api/dependencies.py`, `services/auth_service.py`

## Request handling

- [x] APPSEC-06 Request ceilings: per-IP limit on every endpoint (120/min), body-size limit, per-key and per-tier limits — `middleware/ip_rate_limit_middleware.py`, `middleware/body_size_limit_middleware.py`, `config/platform_settings.py`
- [x] APPSEC-07 Unhandled errors return a generic 500 with a request ID, never a stack trace; docs and OpenAPI are off in production — `api/error_handlers.py:50`, `main.py:83`
- [x] APPSEC-08 SQL built through SQLAlchemy with bound parameters; the one f-string statement uses a constant table name — `core/storage/business_db_probe.py:59`
- [x] APPSEC-09 No user-controlled outbound URLs (SSRF): the backend calls only configured endpoints (LLM SDKs, model server, alert webhook, readiness probe) — `httpx` use in `core/infrastructure/alert_notifier.py`, `services/alert_monitor_service.py`
- [x] APPSEC-10 Security headers: the API sets `nosniff`, HSTS and a deny-all CSP with `frame-ancestors 'none'`; Caddy adds HSTS and a strict CSP on the admin site — `middleware/security_headers_middleware.py`, `deploy/Caddyfile`

## Configuration and secrets

- [x] APPSEC-11 Production refuses to start with weak secrets, `CORS_ORIGINS=*`, the stub LLM or a missing model-server token — `config/settings.py` (`Config.problems`, `Config.validate`)
- [~] APPSEC-12 No secrets in the repository — `.env`, `SSL/` and `*.pem` are gitignored and excluded from images, but GitHub secret scanning and push protection are **off** on this public repository (repository settings → Code security); turn both on, they are free for public repositories
- [x] APPSEC-13 Every admin write is audited with secrets redacted — `middleware/admin_audit_middleware.py`, `services/audit_service.py`

## Containers

- [~] APPSEC-14 Containers run unprivileged — backend and widget images run as a non-root user and compose sets `no-new-privileges`; the admin image (`caddy:2-alpine`) runs as root, and the backend copies the app with `--chown=app:app`, so the API process can rewrite its own code (`backend/Dockerfile`); make the code root-owned and read-only
- [ ] APPSEC-15 Containers drop capabilities and use read-only root filesystems where possible — no `cap_drop` or `read_only` in `docker-compose.yml`
