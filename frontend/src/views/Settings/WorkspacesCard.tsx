import { useCallback, useEffect, useState } from 'react'
import { Card, Chip, SectionLabel } from '../../components/primitives'
import ConfirmDialog from '../../components/ConfirmDialog'
import WorkspaceDialog from '../../components/WorkspaceDialog'
import { deleteWorkspace, fetchWorkspaces, updateWorkspace, type Workspace } from '../../lib/api'
import { accentTextBtnStyle, deleteBtnStyle } from './shared'

export function WorkspacesCard() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [editing, setEditing] = useState<Workspace | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Workspace | null>(null)

  const load = useCallback(() => { fetchWorkspaces(true).then(d => setWorkspaces(d.workspaces)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  const setArchived = async (id: string, archived: boolean) => { await updateWorkspace(id, { archived }); load() }
  const confirmDelete = async () => {
    if (!deleteTarget) return
    await deleteWorkspace(deleteTarget.id)
    setDeleteTarget(null)
    load()
  }

  const active = workspaces.filter(w => !w.archived)
  const archived = workspaces.filter(w => w.archived)

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>Workspaces</SectionLabel>
        <button onClick={() => setShowAdd(true)} style={accentTextBtnStyle({ marginLeft: 'auto' })}>+ Add workspace</button>
      </div>
      {active.length === 0 && (
        <div style={{ textAlign: 'center', padding: 12, color: 'var(--mut)', fontSize: 13 }}>No workspaces yet.</div>
      )}
      {active.map(w => (
        <div key={w.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--mut)', minWidth: 80 }}>{w.id}</span>
          <span style={{ fontSize: 13, color: 'var(--ink)', flex: 1 }}>{w.name}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' }}>{w.repository || '—'}</span>
          <Chip mono soft>{w.runtime || 'global'}</Chip>
          <button onClick={() => setEditing(w)} style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--acc)' }}>Edit</button>
          <button onClick={() => setArchived(w.id, true)} style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--mut)' }}>Archive</button>
          <button onClick={() => setDeleteTarget(w)} style={deleteBtnStyle}>✕</button>
        </div>
      ))}

      {archived.length > 0 && (
        <>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--mut)', margin: '14px 0 4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Archived</div>
          {archived.map(w => (
            <div key={w.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)', opacity: 0.6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--mut)', minWidth: 80 }}>{w.id}</span>
              <span style={{ fontSize: 13, color: 'var(--ink)', flex: 1 }}>{w.name}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' }}>{w.repository || '—'}</span>
              <button onClick={() => setArchived(w.id, false)} style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--acc)' }}>Unarchive</button>
              <button onClick={() => setDeleteTarget(w)} style={deleteBtnStyle}>✕</button>
            </div>
          ))}
        </>
      )}

      {(showAdd || editing) && (
        <WorkspaceDialog
          workspace={editing}
          onClose={() => { setShowAdd(false); setEditing(null) }}
          onSaved={() => { setShowAdd(false); setEditing(null); load() }}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete this workspace?"
        message={deleteTarget ? `Delete workspace "${deleteTarget.name}"? This cannot be undone. Tasks already assigned to it are not deleted.` : ''}
        confirmLabel="Delete"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </Card>
  )
}
