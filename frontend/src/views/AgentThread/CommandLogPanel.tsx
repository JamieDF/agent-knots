import { PanelEmptyState, PanelHeader } from './shared'
import type { CommandEntry } from './types'

export function CommandLogPanel({ commands }: { commands: CommandEntry[] }) {
  return (
    <div>
      <PanelHeader>{commands.length} command{commands.length !== 1 ? 's' : ''} run</PanelHeader>
      {commands.length === 0 && <PanelEmptyState>Shell commands the agent runs will appear here, with the time each one ran.</PanelEmptyState>}
      {commands.map((c, i) => {
        const ts = new Date(c.timestamp)
        const tsStr = `${String(ts.getHours()).padStart(2, '0')}:${String(ts.getMinutes()).padStart(2, '0')}:${String(ts.getSeconds()).padStart(2, '0')}`
        return (
          <div key={i} style={{ display: 'flex', gap: 8, padding: '6px 10px', borderBottom: '1px solid var(--line)', fontSize: 11 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--mut2)', flexShrink: 0 }}>{tsStr}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink2)', wordBreak: 'break-all' }}>{c.command}</span>
          </div>
        )
      })}
    </div>
  )
}
