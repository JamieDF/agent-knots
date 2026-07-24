# agent-knots web cockpit (frontend)

Vite + React 19 + TypeScript SPA — the "Atelier" cockpit redesign. See the
main [`README.md`](../README.md) for what agent-knots does; this file is
about developing the frontend itself.

## Develop

The backend (`agent-knots launch --web --port 8080`) must be
running separately — the dev server proxies `/api` and `/login` to it
(see `vite.config.ts`).

```bash
# terminal 1 — backend
uv run agent-knots launch --web --port 8080

# terminal 2 — frontend, with hot reload
cd frontend
npm install
npm run dev
# → http://127.0.0.1:5173
```

For a production-style check (serves the built bundle from the backend
itself, no separate dev server):

```bash
cd frontend && npm run build   # writes dist/, served by the FastAPI app
```

## Structure

```
src/
├── views/          # One component per route: Dashboard, Tasks (Board/List
│                    # tabs), TaskDetail, AgentThread (Terminal/Files/
│                    # Commands/Browser right-rail tabs), Review, Workflows,
│                    # Settings (Vault + Accessibility are sections within it), tasks/
├── components/      # Shared UI: Topbar, dialogs (TaskDialog,
│                    # WorkspaceDialog, NewSessionDialog, ConfirmDialog),
│                    # Markdown, DeskLayout, primitives/ (Card, Chip, Toggle, ...)
├── lib/              # api.ts (REST client), sse.ts (EventSource wrapper),
│                    # workspaceContext.tsx (scope), stages.ts, theme
├── theme/            # Light/dark ThemeContext, AccessibilityContext (font
│                    # size/family, applied app-wide via `zoom` + a CSS var)
└── main.tsx          # BrowserRouter route table
```

## Design tokens

Light/dark tokens live in `src/index.css` (`--bg`, `--card`, `--ink`,
`--acc`, status/priority colors, etc.), applied via
`body[data-theme="dark"]`. Toggle with the topbar's theme button, backed
by `theme/ThemeContext.tsx` (persists to `localStorage`).

## Live events (SSE)

`lib/sse.ts` wraps `EventSource` against `GET /api/agent/{id}/events`.
Wire format is structured JSON (`events.py::serialize_event()` on the
backend) — the frontend owns all rendering, there's no pre-rendered HTML
from the server. `AgentThread.tsx` merges consecutive same-type
message/thinking deltas into one growing bubble rather than rendering
each raw delta as its own bubble (needed for markdown that spans a delta
boundary to render correctly).

## Tests

```bash
# Type check
npx tsc --noEmit

# Lint
npm run lint

# Playwright e2e — needs a running backend on 127.0.0.1:8090 (see
# playwright.config.ts's baseURL); point HOME at an isolated directory
# first so tests don't touch your real ~/.agent-knots data
rm -rf /tmp/pw-test-home && mkdir -p /tmp/pw-test-home
HOME=/tmp/pw-test-home uv run agent-knots launch --web --port 8090 &

# The test-code (cockpit.spec.ts's getToken()) also reads the cookie
# token from $HOME/.agent-knots/cockpit.token, so HOME needs to be set
# for the `npx playwright test` process too, not just the server above
# — a shell prefix only applies to that one command. But Playwright
# itself also uses $HOME to find its own installed browser
# (~/.cache/ms-playwright), so overriding it wholesale breaks browser
# launch ("Executable doesn't exist…") — pass PLAYWRIGHT_BROWSERS_PATH
# pointed at your real cache alongside the fake HOME to fix both at once:
HOME=/tmp/pw-test-home PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright" \
  npx playwright test
```

A handful of tests need a real LLM provider configured and are expected
to fail without one — see `cockpit.spec.ts` for which ones.
