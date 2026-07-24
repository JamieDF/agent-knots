# Contributing to agent-knots

Thanks for your interest in contributing! agent-knots is a young project and
contributions of all kinds are welcome — code, documentation, bug reports,
feature ideas.

## Code of conduct

Be respectful, assume good faith, focus on the technical.

## Where to start

- **Look at the issue tracker.** Issues tagged
  [`good first issue`](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
  are scoped for newcomers.
- **Read [`docs/architecture.md`](docs/architecture.md).** Understanding
  the architecture is essential before changing interfaces.
- **Run the tests.** `uv run pytest` should pass on `main`. If it doesn't,
  that's a bug — please open an issue.

## Development setup

```bash
git clone https://github.com/jamiedf/agent-knots.git
cd agent-knots
uv sync
uv run pytest
```

You'll need Python 3.14+ and [`uv`](https://docs.astral.sh/uv/). For
frontend work, you'll also need Node.js:

```bash
cd frontend && npm install && npm run dev
```

Run the CLI/cockpit against your local checkout with:

```bash
uv run agent-knots version
uv run agent-knots launch --web
```

## Project layout

See [`docs/architecture.md`](docs/architecture.md#package-layout) for the
full layout. The short version:

- `src/agent_knots/cli/` — Typer CLI entry point and subcommands
- `src/agent_knots/session/` — `SessionManager`, runtimes, Strands features
- `src/agent_knots/cockpit/` — FastAPI web server + Textual TUI
- `src/agent_knots/{task,project,vault,tools}/` — models + YAML/crypto stores
- `frontend/` — Vite + React web cockpit SPA
- `tests/` — Python unit tests (mirrors `src/agent_knots/` package layout)
- `frontend/tests/` — Playwright e2e tests
- `docs/` — architecture, decision records, roadmap

## Coding conventions

### Style

- `ruff check` and `ruff format` clean (config in `pyproject.toml`;
  `select = ["E", "F", "I", "N", "W", "UP"]`, 100-char lines).
- `mypy` clean where feasible — the codebase isn't fully typed yet, but new
  code should carry type hints.
- Frontend: `oxlint` (`npm run lint` in `frontend/`).

### Naming

- Modules are short, lowercase, single-word where possible
  (`vault`, `task`, `project`).
- Store classes are named `<Thing>Store` (`TaskStore`, `ProjectStore`,
  `VaultStore`). Runtime implementations are named by what they back
  (`InProcessRuntime`, `SubprocessRuntime`).
- Tests live under `tests/`, mirroring the package they cover
  (`src/agent_knots/task/store.py` → `tests/test_task/test_store.py`).

### Errors

Raise `ValueError` for invalid input the caller should handle (e.g.
duplicate IDs, malformed data) and let CLI commands catch it and print a
clean message via `typer.Exit(1)`. Don't introduce a custom exception
hierarchy unless a specific failure mode needs to be distinguished by
callers.

### Async

`SessionManager` and the FastAPI web server are async (`asyncio`). Session
lifecycle methods (`start`, `stop`, `set_mode`) are coroutines; CLI
commands that call them wrap with `asyncio.run(...)`.

### Tests

We use `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"` — async test
functions just work, no decorator needed). Prefer plain `assert` and
descriptive test names over table-driven boilerplate:

```python
async def test_vault_locks_after_wrong_passphrase(tmp_path):
    store = VaultStore(tmp_path)
    store.unlock("correct-passphrase")
    store.lock()
    with pytest.raises(ValueError):
        store.unlock("wrong-passphrase")
```

### Documentation

Module-level docstrings should say what the module is for, not restate the
filename. Function/method docstrings are only needed where the *why* isn't
obvious from the signature and body — don't pad every function with a
docstring that just repeats its name.

## Pull request process

1. **Open an issue first** for non-trivial changes. Discuss the approach
   before writing code.
2. **Fork the repo** and create a branch from `main`.
3. **Write tests.** PRs without tests are unlikely to merge.
4. **Update docs** if you're changing user-facing behavior. The README and
   architecture doc both matter.
5. **Run the full check suite** before pushing:
   ```bash
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src/agent_knots
   ```
6. **One logical change per commit.** Squash fixup commits. Write commit
   messages in the imperative mood ("Add vault credential import", not
   "Added").
7. **Open a PR** against `main`. There's no CI configured yet (tracked on
   the [roadmap](roadmap.md)) — run the checks above locally before
   requesting review.

## Release process

We use [Semantic Versioning](https://semver.org/). Versions are tagged
manually after the check suite passes locally:

```bash
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

There's no packaged release/installer yet — see the
[roadmap](roadmap.md).

## Decision records

Significant architectural decisions are recorded as ADRs in
[`docs/decisions/`](docs/decisions/). Some predate the Python rebuild and
record decisions made for the original Go implementation — read the note
at the top of each ADR before relying on its specifics. Read these before
proposing changes that affect core interfaces.

## License

By contributing, you agree that your contributions will be licensed under
the [MIT License](LICENSE).

## Getting help

- **GitHub Issues** for bugs and feature requests
- **GitHub Discussions** for questions and design discussion
- **Code review** on your PR — open one early, even as a draft

We're a small project, so responses may take a day or two. Patience is
appreciated. 🙏
