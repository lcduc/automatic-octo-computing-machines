# Admin web

The management console for the chatbot, shared by every deployment: knowledge base (documents, sources,
chunking strategies, preview and re-chunk), conversations, feedback, handoffs, logs, settings (answers,
models and retrieval, widget look), accounts and API keys, and the audit log.

It is a static React + TypeScript single-page app (Vite, React Router). It talks only to the backend's
admin API at `/api/v1/admin` on its **own origin**, so the backend's HttpOnly session cookie works without
CORS and the console never shares a host with the embeddable chat.

## Develop

```bash
cd frontends/admin
npm ci
npm run dev          # http://localhost:5174, proxies /api/v1/admin to BACKEND_URL (default http://127.0.0.1:8500)
```

Run the API with `APP_ENV=development` (the session cookie is only `Secure` in production) and create an
owner once: `python -m scripts.manage create-admin --email you@example.com --role owner`.

```bash
npm run lint         # oxlint, incl. jsx-a11y
npm run typecheck    # tsc --noEmit (strict)
npm test             # vitest
npm run build        # dist/
```

## Deploy

`docker compose` builds this folder as the `admin` service; the public Caddy serves it on `ADMIN_DOMAIN`
with a strict CSP (`frame-ancestors 'none'`) and proxies only `/api/v1/admin/*` to the API.

## Conventions

- Design tokens (`src/styles/tokens.css`) follow the giz-chatbot palette; screens use the classes in
  `src/styles/components.css`, not inline styles.
- Every string lives in `src/i18n/vi.ts` (default) and `en.ts`; the type system rejects a missing key.
- `src/lib/permissions.ts` mirrors `api/dependencies.py` for showing controls; the backend enforces access.
- No token is ever stored in JavaScript; only the language choice is kept in `localStorage`.
