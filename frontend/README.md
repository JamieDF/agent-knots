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

**Wipe the data directory before every run.** The `rm -rf` above isn't
optional housekeeping — the suite is not idempotent against a dirty
one. Tests create fixtures by title and locate them by text, so a
leftover "Board card test" from a previous run makes
`.ak-card:has-text(...)` resolve to two elements and the run fails on a
strict-mode violation that looks nothing like the real problem. If you
see "resolved to 2 elements", suspect a stale data dir before anything
else.

A handful of tests need a real LLM provider configured and are expected
to fail without one — see `cockpit.spec.ts` for which ones. With a
provider configured the whole suite passes (74 passed, 2 skipped);
without one, expect roughly ten extra failures, all in the tests that
drive a live agent.

### Isolating with HOME vs AGENT_KNOTS_HOME

`HOME=/tmp/pw-test-home` is the right lever for the e2e suite, because
the test code itself reads the cookie token out of
`$HOME/.agent-knots/`. It is the wrong lever for anything that needs
git over SSH — ssh looks for keys in `$HOME/.ssh`, so a server launched
with a fake HOME cannot clone a private repo and fails with a bare
authentication error.

For manual testing against a real remote, isolate with
`AGENT_KNOTS_HOME` instead: it moves every scrap of agent-knots state
(including managed workspace clones, which follow it — see
`config.workspaces_root()`) while leaving `$HOME` real so SSH keeps
working.

```bash
AGENT_KNOTS_HOME=/tmp/ak-test uv run agent-knots launch --web --port 8091
```
