import type { SSEEvent } from '../../lib/sse'

export interface EventItem extends SSEEvent { id: number; result?: SSEEvent }
export type Tab = 'terminal' | 'files' | 'commands' | 'browser'

export interface BrowserTab { id: string; url: string }

export function newBrowserTabId(): string {
  return `tab-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

export interface FileChange { path: string; action: string; timestamp: number }
export interface CommandEntry { command: string; timestamp: number }

/** Pure event-accumulation reducer, shared by the top-level thread and
 * DelegateSubThread (a delegated sub-agent's nested mini-thread).
 * DelegateSubThread used to append every raw event with no accumulation
 * at all, so a sub-agent's thread rendered as a dozen tiny fragment
 * bubbles and duplicate tool cards even after the top-level thread got
 * fixed for the same problem — sharing this reducer keeps both in sync.
 * Handles three things:
 *  - a tool call streams in incrementally (the backend re-emits the
 *    whole tool_call event, same id, as its args accumulate) — updates
 *    the existing card in place instead of appending a duplicate;
 *  - merges a tool_result into the most recent unresolved tool_call by
 *    adjacency (tool_call_id linkage isn't reliably populated
 *    backend-side yet, see events.py::TOOL_RESULT construction);
 *  - message/thinking stream in as many small text deltas, each its own
 *    event — accumulates consecutive same-type deltas into the prior
 *    bubble instead of a dozen fragments (also needed so markdown
 *    spanning a delta boundary, e.g. "**bold**" split across two
 *    deltas, renders correctly instead of as literal asterisks).
 */
export function reduceEvent(prev: EventItem[], evt: SSEEvent, nextId: number, cap = 300): EventItem[] {
  if (evt.type === 'tool_call' && evt.tool_call) {
    const callId = evt.tool_call.id
    for (let i = prev.length - 1; i >= 0; i--) {
      if (prev[i].type === 'tool_call' && prev[i].tool_call?.id === callId) {
        const next = [...prev]
        next[i] = { ...next[i], tool_call: evt.tool_call, timestamp: evt.timestamp }
        return next
      }
    }
  }
  if (evt.type === 'tool_result') {
    for (let i = prev.length - 1; i >= 0; i--) {
      if (prev[i].type === 'tool_call' && !prev[i].result) {
        const next = [...prev]
        next[i] = { ...next[i], result: evt }
        return next
      }
    }
  }
  if ((evt.type === 'message' || evt.type === 'thinking') && prev.length > 0) {
    const last = prev[prev.length - 1]
    if (last.type === evt.type) {
      const next = [...prev]
      next[next.length - 1] = { ...last, message: (last.message || '') + (evt.message || ''), timestamp: evt.timestamp }
      return next
    }
  }
  return [...prev.slice(-cap), { ...evt, id: nextId }]
}

// editor's `command` arg tells us read vs. write — 'view'/'find_line'
// don't touch the file, everything else does (create is a genuinely new
// file, the rest modify an existing one).
const EDITOR_WRITE_COMMANDS = new Set(['create', 'str_replace', 'pattern_replace', 'insert', 'undo_edit'])

/** Only the editor tool belongs on the Files tab — shell commands often
 * reference something that looks like a filename in their args ("cat
 * notes.txt") without it being a real file touch the way an edit/read
 * is, and mixing the two made the tab list commands, not files. */
export function recordFileTouch(toolCall: NonNullable<SSEEvent['tool_call']>, setFiles: (fn: (prev: FileChange[]) => FileChange[]) => void) {
  if (toolCall.name !== 'editor') return
  const path = toolCall.args.path
  if (typeof path !== 'string' || !path) return
  const command = typeof toolCall.args.command === 'string' ? toolCall.args.command : ''
  const action = command === 'create' ? 'write' : EDITOR_WRITE_COMMANDS.has(command) ? 'edit' : 'read'
  setFiles(prev => {
    const next = prev.filter(f => f.path !== path)
    return [...next.slice(-49), { path, action, timestamp: Date.now() }]
  })
}

/** Command Log — every shell invocation with its own timestamp, kept
 * separate from Terminal (a real interactive shell) and from Files
 * (editor-only touches). shell's `command` arg can be a single string
 * or a list (parallel commands), so this can log more than one entry
 * per tool call. */
export function recordCommand(toolCall: NonNullable<SSEEvent['tool_call']>, setCommands: (fn: (prev: CommandEntry[]) => CommandEntry[]) => void) {
  if (toolCall.name !== 'shell') return
  const raw = toolCall.args.command
  const cmds: string[] = Array.isArray(raw)
    ? raw.map(c => (typeof c === 'string' ? c : (c as Record<string, unknown>)?.command)).filter((c): c is string => typeof c === 'string')
    : typeof raw === 'string' ? [raw] : []
  if (cmds.length === 0) return
  const timestamp = Date.now()
  setCommands(prev => [...prev.slice(-199), ...cmds.map(command => ({ command, timestamp }))])
}
