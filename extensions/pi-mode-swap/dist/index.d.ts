/**
 * Pi extension for agent-knots: runtime mode/persona swap.
 *
 * Registers the `/agent-knots-switch` slash command. When invoked via
 * Pi's RPC mode (`{"type":"prompt","message":"/agent-knots-switch assistant"}`),
 * the extension reads the system prompt from a mode file and swaps
 * the agent's persona + thinking level.
 *
 * Mode files are expected at `/workspace/.agent-knots/modes/<mode>.md`
 * (mounted into the container via the podman container runtime).
 *
 * Thinking-level mapping:
 *   agent     → "high"   (autonomous, works to completion)
 *   assistant → "low"    (interactive, waits for user)
 *   reviewer  → "medium" (balanced, read-only)
 *   security  → "high"   (thorough analysis)
 *   junior-dev → "low"  (cautious)
 *   senior-dev → "high"  (confident)
 *   planner   → "medium"
 *   debugger  → "high"
 *   documenter → "medium"
 *   refactorer → "high"
 *   test-writer → "high"
 *
 * Usage from agent-knots's control channel:
 *   When the session subprocess receives a `set-mode` control message,
 *   it sends `{"type":"prompt","message":"/agent-knots-switch <mode>"}\n`
 *   to Pi's stdin. Pi dispatches to this extension.
 */
export default function (pi: any): void;
