# `backend/app/middleware/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
App-wide HTTP middleware, one class per file, written as plain ASGI (not Starlette
`BaseHTTPMiddleware`) so streaming responses and the `contextvars` request id behave correctly.
Only `app/main.py` imports this package. Logic for a single feature does not belong here: per-route
auth is a FastAPI dependency in `app/api/dependencies.py`, rate-limit and audit rules live in
`services/`.

## Files
| File | Public names | What it does |
|---|---|---|
| `__init__.py` | `AdminAuditMiddleware`, `BodySizeLimitMiddleware`, `IpRateLimitMiddleware`, `RequestContextMiddleware`, `SecurityHeadersMiddleware` | Re-exports the classes; its docstring records the registration order. |
| `admin_audit_middleware.py` | `AdminAuditMiddleware`, `ADMIN_API_PREFIX`, `AUDITED_METHODS`, `AUDIT_MAX_BODY_BYTES`, `LOGIN_PATH_SUFFIX` | For POST/PUT/PATCH/DELETE under `/api/v1/admin/`, captures request and response (JSON up to 16 KiB, else a size summary) and writes an `AuditRecord` after the response via `container.audit`. Actor = the principal `require_admin` put on `request.state.admin`; for sign-ins, the submitted e-mail. A write failure is logged, never raised. |
| `asgi_helpers.py` | `header_value`, `send_json`, `QUIET_PATH_PREFIXES` | Shared helpers: read one request header; send a complete JSON response from inside middleware. `/health` paths are "quiet" (not rate limited, not logged). |
| `body_size_limit_middleware.py` | `BodySizeLimitMiddleware`, `BODY_OVERHEAD_BYTES` | 413 when `Content-Length` exceeds `MAX_FILE_SIZE` + 1 MiB; also counts streamed bytes and aborts the body when it goes over. |
| `ip_rate_limit_middleware.py` | `IpRateLimitMiddleware` | Per-client-IP requests per minute (`RATE_LIMIT_IP_PER_MINUTE`) through `container.rate_limiter` (PostgreSQL time buckets); 429 with `Retry-After`. If the counter store fails, the request is let through and the error logged. |
| `request_context_middleware.py` | `RequestContextMiddleware`, `REQUEST_ID_PATTERN` | Reuses a valid incoming `X-Request-ID` (8–64 chars `[A-Za-z0-9-]`) or makes one, binds it to `utils.request_context.request_id_var` for logs, echoes it in the response and logs one line per request (method, path, status, ms). |
| `security_headers_middleware.py` | `SecurityHeadersMiddleware`, `DOCS_PATH_PREFIXES`, `HSTS_VALUE` | Adds `nosniff`, `X-Frame-Options: DENY`, referrer and permissions policies, `CSP default-src 'none'; frame-ancestors 'none'` (skipped on `/docs`, `/redoc`, `/openapi.json`), and HSTS in production. |

Order (outermost first, as registered in `main.py`): CORS -> request context -> security headers ->
body size limit -> per-IP rate limit -> admin audit -> routes. CORS is outermost so 401/413/429
responses still carry CORS headers; request context comes next so every later log line has the id.

## Dependencies
- May import: `services` (`AuditRecord`, `rate_limit_service.Limit`/`hashed`), `core` (usage window
  constants), `utils.request_context`, `config`. Never `api`. Only `main.py` may import this package
  (layering: api -> services -> core -> models/utils, config at the bottom; enforced by
  `test/unit/test_layering.py`).
- Used by: `app/main.py` only. At runtime the audit and rate-limit middleware read the service
  container from `scope["app"].state.container`; before the lifespan has built it they pass through.
- External: PostgreSQL (rate-limit counters, audit table) through the container's services.

## Run / test
```bash
pytest test/integration/test_api.py -k "security_headers or audited or rate_limit or csrf"   # needs TEST_DATABASE_URL
pytest test/unit/test_audit_redaction.py
```

## Known problems and history
- Middleware moved out of the API package into its own package (3b8c60d, 2026-09-28).
- Rate limits switched from process memory to PostgreSQL time buckets (ed7a595, 2026-09-29).
- Backend moved under `backend/app` (lcduc/automatic-octo-computing-machines#76, 2026-11-10).
- `test_api.py::test_rate_limit_and_roles` is timing-flaky (per-minute rate-limit window); passes
  on rerun.
- `AdminAuditMiddleware` docstring now lists PUT and the `ADMIN_API_PREFIX` comment says
  `api/v1/routes` (branch `refactor/structure-fixes`, 2026-11-10).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none.
- Ceilings (`# ceiling:` markers in this folder): none.
