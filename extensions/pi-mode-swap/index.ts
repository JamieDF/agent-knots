/**
 * Pi extension for agentjam: runtime mode/persona swap.
 *
 * Registers the `/agentjam-switch` slash command. When invoked via
 * Pi's RPC mode (`{"type":"prompt","message":"/agentjam-switch assistant"}`),
 * the extension reads the system prompt from a mode file and swaps
 * the agent's persona + thinking level.
 *
 * Mode files are expected at `/workspace/.agentjam/modes/<mode>.md`
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
 * Usage from agentjam's control channel:
 *   When the session subprocess receives a `set-mode` control message,
 *   it sends `{"type":"prompt","message":"/agentjam-switch <mode>"}\n`
 *   to Pi's stdin. Pi dispatches to this extension.
 */

// Mode-to-thinking-level map.
const THINKING_LEVELS: Record<string, string> = {
  agent: "high",
  assistant: "low",
  reviewer: "medium",
  security: "high",
  "junior-dev": "low",
  "senior-dev": "high",
  planner: "medium",
  debugger: "high",
  documenter: "medium",
  refactorer: "high",
  "test-writer": "high",
};

// Fallback thinking level if mode is unknown.
const FALLBACK_THINKING = "medium";

// Path where mode markdown files are mounted inside the container.
const MODES_DIR = "/workspace/.agentjam/modes";

/**
 * Read the content of a mode markdown file.
 */
async function readModeFile(mode: string): Promise<string> {
  // Pi extensions run in a Deno-like environment with Deno.readTextFile.
  const path = `${MODES_DIR}/${mode}.md`;
  const Deno = (globalThis as any).Deno;
  if (!Deno?.readTextFile) {
    throw new Error(`Deno.readTextFile not available — cannot read mode file for "${mode}"`);
  }
  try {
    return await Deno.readTextFile(path);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(`Failed to read mode file for "${mode}": ${msg}`);
  }
}

/**
 * Get the thinking level for a given mode.
 */
function modeToThinkingLevel(mode: string): string {
  return THINKING_LEVELS[mode] ?? FALLBACK_THINKING;
}

// The Pi extension entry point.
export default function (pi: any) {
  pi.registerCommand("agentjam-switch", {
    description: "Switch agent mode/persona (called by agentjam orchestrator)",
    execute: async (args: string) => {
      const mode = args.trim();
      if (!mode) {
        return "Usage: /agentjam-switch <mode>  (e.g. agent, assistant, reviewer)";
      }

      try {
        // Read the mode's system prompt.
        const prompt = await readModeFile(mode);

        // Get the agent session handle.
        // Pi exposes this on the extension API (`pi.agentSession` or similar).
        const session = (pi as any).agentSession ?? (pi as any).session;
        if (!session || typeof session.setSystemPrompt !== "function") {
          return `Mode file loaded (${prompt.length} chars), but agent session handle not available. Mode content prepared for next restart.`;
        }

        // Swap the system prompt.
        await session.setSystemPrompt(prompt);

        // Swap the thinking level.
        const level = modeToThinkingLevel(mode);
        if (typeof session.setThinkingLevel === "function") {
          await session.setThinkingLevel(level);
        }

        return `Switched to ${mode} mode (thinking: ${level})`;
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return `Error switching mode: ${msg}`;
      }
    },
  });

  // Also register a "pause" command that aborts the agent.
  pi.registerCommand("agentjam-pause", {
    description: "Pause the agent (called by agentjam orchestrator)",
    execute: async () => {
      try {
        const session = (pi as any).agentSession ?? (pi as any).session;
        if (session && typeof session.abort === "function") {
          await session.abort();
        }
        return "Agent paused.";
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return `Error pausing: ${msg}`;
      }
    },
  });
}
