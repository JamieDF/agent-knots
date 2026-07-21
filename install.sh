#!/usr/bin/env bash
#
# agent-knots installer.
#
# Run from inside a cloned checkout:
#   git clone https://github.com/jamiedf/agent-knots.git
#   cd agent-knots
#   ./install.sh
#
# Installs uv if missing, syncs Python dependencies, builds the web
# cockpit frontend (if Node is available), and installs the `agent-knots`
# command globally via `uv tool install`. Safe to re-run.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

info() { printf -- '→ %s\n' "$1"; }
ok()   { printf -- '✓ %s\n' "$1"; }
warn() { printf -- '⚠ %s\n' "$1" >&2; }
die()  { printf -- '✗ %s\n' "$1" >&2; exit 1; }

echo "agent-knots install"
echo "===================="
echo ""

# ── uv ────────────────────────────────────────────────────────────────

if ! command -v uv &>/dev/null; then
    info "uv not found — installing (https://docs.astral.sh/uv/)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Pick up uv on PATH for the rest of this script without a new shell.
    [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv &>/dev/null || die "uv install finished but 'uv' still isn't on PATH. Open a new shell and re-run ./install.sh."
fi
ok "uv found: $(uv --version)"

# ── python dependencies ──────────────────────────────────────────────

info "Installing Python dependencies (uv sync)..."
uv sync
ok "Python dependencies installed"

# ── frontend ─────────────────────────────────────────────────────────

if command -v npm &>/dev/null; then
    info "Building the web cockpit frontend..."
    ( cd frontend && npm install && npm run build )
    ok "Frontend built"
else
    warn "npm not found — skipping the web cockpit frontend build."
    warn "The web cockpit will fall back to a minimal shell with no setup wizard."
    warn "Install Node.js (https://nodejs.org), then run: cd frontend && npm install && npm run build"
fi

# ── CLI command ──────────────────────────────────────────────────────

info "Installing the agent-knots command (uv tool install)..."
uv tool install --editable . --reinstall
ok "agent-knots command installed"

# ── done ─────────────────────────────────────────────────────────────

echo ""
echo "===================="
if command -v agent-knots &>/dev/null; then
    ok "Install complete."
else
    ok "Install complete, but 'agent-knots' isn't on PATH in this shell yet."
    warn 'Add this to your shell profile (~/.bashrc, ~/.zshrc, ...), then open a new shell:'
    warn '  export PATH="$HOME/.local/bin:$PATH"'
fi
echo ""
echo "Next:"
echo "  agent-knots cockpit launch --web"
echo ""
echo "First launch opens a setup wizard to configure your model provider"
echo "(API key, model, base URL) in the browser."
echo ""
echo "To skip the wizard — scripted installs, CI, containers — either:"
echo "  - export AGENT_KNOTS_API_KEY=... AGENT_KNOTS_MODEL=... before launch, or"
echo "  - write ~/.agent-knots/settings.yaml before first launch (see docs/quickstart.md)"
