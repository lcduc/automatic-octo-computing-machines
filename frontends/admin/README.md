# Admin web

The management console for the chatbot, shared by every deployment: a demo chat and a live preview of the
embeddable widget, knowledge base (documents, sources, chunking strategies, preview and re-chunk),
conversations, feedback, handoffs, logs, settings (answers, models and retrieval, widget look), accounts,
roles and API keys, and the audit log. The layout follows the giz-chatbot management web.

It is a static React + TypeScript single-page app (Vite, React Router). It talks only to the backend's
admin API at `/api/v1/admin` on its **own origin**, so the backend's HttpOnly session cookie works without
CORS and the console never shares a host with the embeddable chat.

## Develop

```bash
cd frontends/admin
npm ci
npm run dev          # http://localhost:5174, proxies /api/v1/admin to BACKEND_URL (default http://127.0.0.1:8500)
```

The demo chat (`/chat`) talks to the chat widget's server through `/api/chat` (proxied to `WIDGET_URL`,
default `http://127.0.0.1:3000`; behind Caddy on the admin domain), so it runs the exact visitor pipeline
and its sessions appear under Conversations. The widget preview (`/widget`) frames `<widget origin>/widget`,
read at run time from `/runtime-config.json` (`public/` in dev, `WIDGET_ORIGIN` in the image); the widget
server must list the admin's origin in `WIDGET_ALLOWED_PARENTS`.

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
- No token is ever stored in JavaScript; only the language and theme choices are kept in `localStorage`.
- Light and dark themes: colours come only from `src/styles/tokens.css`, redefined under
  `:root[data-theme="dark"]` (set by `src/lib/theme.tsx`; Light, Dark or follow the system).
