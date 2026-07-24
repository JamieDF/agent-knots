import { useEffect, useRef, useState } from 'react'
import { fetchWorkspaces, type Workspace } from '../lib/api'
import { useClickOutside } from '../lib/useClickOutside'
import { useWorkspaceScope } from '../lib/workspaceContext'

/** Workspace scope switcher — a pill button + dropdown, matching the
 * rest of the topbar instead of a bare native <select>. */
function WorkspaceSwitcher() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [open, setOpen] = useState(false)
  const { workspace, setWorkspace } = useWorkspaceScope()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => { fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {}) }, [])

  // Refetch whenever the dropdown opens — this component's list is only
  // ever loaded once on mount otherwise, so a workspace created elsewhere
  // (e.g. Settings) wouldn't show up here until a full page reload.
  useEffect(() => {
    if (open) fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {})
  }, [open])

  useClickOutside(ref, open, () => setOpen(false))

  const current = workspaces.find(w => w.id === workspace)
  const label = current ? current.name : 'All workspaces'

  const choose = (id: string) => { setWorkspace(id); setOpen(false) }

  return (
    <div ref={ref} style={{ position: 'relative', marginLeft: 8 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', borderRadius: 8,
          fontSize: 12, fontWeight: 600, border: '1px solid var(--line2)', background: 'var(--card2)',
          color: 'var(--ink2)', maxWidth: 180, whiteSpace: 'nowrap',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</span>
        <span style={{ fontSize: 9, color: 'var(--mut)' }}>▾</span>
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, marginTop: 6, minWidth: 200, maxHeight: 320, overflowY: 'auto',
          background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 10,
          boxShadow: 'var(--shadow-lg)', zIndex: 200, padding: 4,
        }}>
          <Row label="All workspaces" active={!workspace} onClick={() => choose('')} />
          {workspaces.map(w => (
            <Row key={w.id} label={w.name} active={workspace === w.id} onClick={() => choose(w.id)} />
          ))}
          {workspaces.length === 0 && (
            <div style={{ padding: '8px 10px', fontSize: 12, color: 'var(--mut)' }}>No workspaces yet.</div>
          )}
        </div>
      )}
    </div>
  )
}

function Row({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: '7px 10px', borderRadius: 6, fontSize: 12.5, cursor: 'pointer',
        color: active ? 'var(--acc)' : 'var(--ink)', fontWeight: active ? 700 : 500,
        background: active ? 'var(--acc-soft)' : 'transparent',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}
    >
      {label}
    </div>
  )
}

export default WorkspaceSwitcher
