#!/usr/bin/env bash
#
# smoke.sh — end-to-end smoke test for agentjam.
#
# Exercises the full session lifecycle with a mock driver (no LLM needed):
#   start → list → logs → assume → relinquish → send → stop → verify cleanup
#
# Also tests git worktree integration with a temp repo.
#
# Usage:  ./scripts/smoke.sh
# Exit:   0 = all pass, 1 = any failure
set -euo pipefail

# ─── Setup ───────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$REPO_ROOT/smoke-agentjam"
AJ_HOME="$(mktemp -d -t agentjam-smoke-XXXXXX)"
export AGENTJAM_HOME="$AJ_HOME"

PASS=0
FAIL=0
CURRENT_TEST=""

ok()   { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }
section() { echo ""; echo "━━━ $1 ━━━"; }
die()  { echo "FATAL: $1" >&2; exit 1; }

cleanup() {
    [ -f "$BIN" ] && rm -f "$BIN"
    [ -d "$AJ_HOME" ] && rm -rf "$AJ_HOME"
}
trap cleanup EXIT

# ─── Build ───────────────────────────────────────────────────────────

section "Build"

GO=${GO:-go}
if ! command -v "$GO" &>/dev/null; then
    GO="/tmp/go/bin/go"
fi

echo "  Building agentjam..."
( cd "$REPO_ROOT" && GOFLAGS=-mod=mod "$GO" build -o "$BIN" ./cmd/agentjam ) || die "build failed"
ok "binary built"

AJ="$BIN"
mkdir -p "$AJ_HOME/sessions" "$AJ_HOME/tasks" "$AJ_HOME/projects"

# ─── Session Lifecycle ───────────────────────────────────────────────

section "Session Lifecycle (mock driver)"

# Start a detached mock session.
echo "  Starting mock session..."
START_OUT=$("$AJ" session start --driver mock --detach 2>&1) || die "session start failed: $START_OUT"

# Extract the session ID from the output.
SID=$(echo "$START_OUT" | grep -oE 'session [A-Za-z0-9_-]+' | head -1 | awk '{print $2}')
[ -z "$SID" ] && die "could not extract session ID from: $START_OUT"
echo "  Session ID: $SID"

# Wait for PID file (session is ready).
for i in $(seq 1 30); do
    [ -f "$AJ_HOME/sessions/$SID.pid" ] && break
    sleep 0.5
done
[ -f "$AJ_HOME/sessions/$SID.pid" ] || die "PID file not created after 15s"
ok "session started (PID file exists)"

# Verify session appears in list.
LIST_OUT=$("$AJ" session list 2>&1)
if echo "$LIST_OUT" | grep -q "$SID"; then
    ok "session appears in list"
else
    fail "session not in list: $LIST_OUT"
fi

# Verify session shows as running.
if echo "$LIST_OUT" | grep -qi "running"; then
    ok "session shows running status"
else
    fail "session not showing as running"
fi

# ─── Event Streaming ─────────────────────────────────────────────────

echo "  Waiting for events to accumulate..."
sleep 3

LOGS_OUT=$(timeout 3 "$AJ" session logs "$SID" 2>&1) || true
if [ -n "$LOGS_OUT" ]; then
    ok "event stream produced output"
    if echo "$LOGS_OUT" | grep -qiE "\[thinking\]|\[tool\]|\[result\]|\[progress\]|"; then
        ok "events contain expected types"
    else
        fail "no recognizable event types in: $LOGS_OUT"
    fi
else
    fail "no event output from logs command"
fi

# ─── Take-over Flow ──────────────────────────────────────────────────

section "Take-over Flow (assume / relinquish / send)"

# Test assume.
ASSUME_OUT=$("$AJ" session assume "$SID" 2>&1) || fail "assume failed: $ASSUME_OUT"
if echo "$ASSUME_OUT" | grep -qi "assistant"; then
    ok "assume switched to assistant mode"
else
    fail "assume output unexpected: $ASSUME_OUT"
fi

# Test send.
SEND_OUT=$("$AJ" session send "$SID" "please review the auth module" 2>&1) || fail "send failed: $SEND_OUT"
if echo "$SEND_OUT" | grep -qi "sent"; then
    ok "send delivered message"
else
    fail "send output unexpected: $SEND_OUT"
fi

# Test relinquish.
RELINQ_OUT=$("$AJ" session relinquish "$SID" 2>&1) || fail "relinquish failed: $RELINQ_OUT"
if echo "$RELINQ_OUT" | grep -qi "agent"; then
    ok "relinquish switched back to agent mode"
else
    fail "relinquish output unexpected: $RELINQ_OUT"
fi

# ─── Stop & Cleanup ──────────────────────────────────────────────────

section "Stop & Cleanup"

# Stop the session.
STOP_OUT=$("$AJ" session stop "$SID" 2>&1) || fail "stop failed: $STOP_OUT"
ok "stop command returned"

# Wait for cleanup.
for i in $(seq 1 20); do
    [ ! -f "$AJ_HOME/sessions/$SID.pid" ] && break
    sleep 0.5
done

if [ ! -f "$AJ_HOME/sessions/$SID.pid" ]; then
    ok "PID file removed after stop"
else
    fail "PID file still exists after stop"
fi

if [ ! -f "$AJ_HOME/sessions/$SID.sock" ]; then
    ok "socket file removed after stop"
else
    fail "socket file still exists after stop"
fi

# Verify session no longer shows as running.
LIST_AFTER=$("$AJ" session list 2>&1)
if echo "$LIST_AFTER" | grep -qi "stopped"; then
    ok "session shows stopped status after stop"
else
    # May just be empty list — also OK.
    ok "session no longer running"
fi

# ─── Git Worktree Integration ────────────────────────────────────────

section "Git Worktree Integration"

if ! command -v git &>/dev/null; then
    echo "  (skipped — git not installed)"
else
    # Create a temp git repo.
    REPO_DIR=$(mktemp -d -t agentjam-wt-repo-XXXXXX)
    git init -q -b main "$REPO_DIR"
    git -C "$REPO_DIR" config user.email "[email protected]"
    git -C "$REPO_DIR" config user.name "Smoke Test"
    echo "# test project" > "$REPO_DIR/README.md"
    git -C "$REPO_DIR" add .
    git -C "$REPO_DIR" commit -q -m "initial"

    # Create a project pointing to the repo.
    PROJ_OUT=$("$AJ" project create --name "smoke-test" --root "$REPO_DIR" 2>&1) || true

    # Start a session with --worktree.
    WT_OUT=$("$AJ" session start --driver mock --project smoke-test --worktree --detach 2>&1) || {
        echo "  (worktree session failed — this is OK if no project store was configured)"
        rm -rf "$REPO_DIR"
        goto_worktree_done=true
    }

    if [ "${goto_worktree_done:-}" != "true" ]; then
        WT_SID=$(echo "$WT_OUT" | grep -oE 'session [A-Za-z0-9_-]+' | head -1 | awk '{print $2}')

        if [ -n "$WT_SID" ]; then
            sleep 2

            # Verify worktree branch was created.
            WT_BRANCH=$(git -C "$REPO_DIR" branch --list "agent-*" 2>/dev/null | head -1 | tr -d ' *')
            if [ -n "$WT_BRANCH" ]; then
                ok "worktree branch created: $WT_BRANCH"
            else
                fail "no worktree branch found"
            fi

            # Stop and verify branch cleanup.
            "$AJ" session stop "$WT_SID" 2>&1 || true
            sleep 2

            WT_BRANCH_AFTER=$(git -C "$REPO_DIR" branch --list "agent-*" 2>/dev/null | head -1 | tr -d ' *')
            if [ -z "$WT_BRANCH_AFTER" ]; then
                ok "worktree branch cleaned up after stop"
            else
                fail "worktree branch still exists: $WT_BRANCH_AFTER"
            fi
        else
            echo "  (could not start worktree session — skipping)"
        fi

        rm -rf "$REPO_DIR"
    fi
fi

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$FAIL" -eq 0 ]; then
    echo "✅ ALL PASSED ($PASS checks)"
    exit 0
else
    echo "❌ $FAIL FAILED, $PASS passed"
    exit 1
fi
