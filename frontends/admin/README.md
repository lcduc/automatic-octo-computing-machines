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

## Files

| Path | What it holds |
|---|---|
| `index.html`, `src/main.tsx`, `src/router.tsx` | Entry point and client-side routes. `src/app.smoke.test.tsx` renders the app once. |
| `src/pages/` | One screen per file or folder: `LoginPage`, `AccessPage` + `access/` (users, role matrix), `AuditPage`, `FeedbackPage` + `feedback/EvalCasesCard.tsx` (golden eval set export for `backend/scripts/eval/rag.py`), `HandoffsPage`, `LogsPage`, `chat/` (demo chat over the widget server), `conversations/`, `knowledge/` (sources, documents, chunks), `overview/` (live feed, token chart, monthly history), `settings/` (chat behaviour, limits, privacy, support, widget look), `widget/` (widget preview). |
| `src/components/` | Shared UI: `layout/` (console shell, sidebar, top bar, theme toggle, password change), `ui/` (modal, toast, primitives, dialog focus), `knowledge/`, `conversations/` (transcript, trace details), `privacy/` (legal hold). |
| `src/lib/` | `api.ts` (admin API client), `sse.ts`, `session.tsx`, `permissions.ts`, `theme.tsx`, `use-api.ts`, `types.ts`, `labels.ts`, `markdown.tsx`, `metadata.ts`, `download.ts`, `use-desktop-notifications.ts`, with `*.test.ts(x)` next to them. |
| `src/i18n/` | `vi.ts`, `en.ts`, `I18nProvider.tsx`. |
| `src/styles/` | `tokens.css` (colours, both themes), `components.css` and per-area stylesheets. |
| `public/runtime-config.json` | Dev value of `widgetOrigin` for the widget preview. |
| `Dockerfile`, `Caddyfile`, `.dockerignore` | Image: Node build stage, then Caddy serving `dist/` on `:80` with SPA fallback, immutable `/assets/*` and `/runtime-config.json` from `WIDGET_ORIGIN`. |
| `vite.config.ts`, `tsconfig.json`, `.oxlintrc.json`, `package.json` | Build, strict TypeScript, oxlint (react, jsx-a11y, vitest plugins), scripts. |
| `.claude/`, `.mcp.json` | Project-level agent skills (`frontend-ui-engineering`, `browser-testing-with-devtools`, checklists, `/webperf`) and Chrome DevTools MCP with `--isolated`. |

## Known problems and history
- Created 2026-09-28 (b5ea5cd); demo chat, widget preview and redesigned console on 2026-09-30 (ad02d4e);
  review queue and knowledge transfer on 2026-10-07 (5a92df9); model-server queue and free VRAM on the overview
  on 2026-10-22 (1e2508e).
- Warning badges and callouts used the accent colours instead of the warning tokens and lost their colour →
  switched to `--status-warning-*` in `components.css` (e2fe6c9, `lcduc/automatic-octo-computing-machines#38`,
  2026-10-08).
- The relevance threshold is hidden from admins (920d1f7, 2026-10-01).
- `EvalCasesCard.tsx`'s comment was updated for the eval scripts' move to `backend/scripts/eval/` (30cfa1c, #76).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none recorded.
- Ceilings (`# ceiling:` markers in this folder): none.
