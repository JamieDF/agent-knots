import { useCallback, useEffect, useState } from 'react'
import { Card, Chip, SectionLabel } from '../../components/primitives'
import ConfirmDialog from '../../components/ConfirmDialog'
import WorkspaceDialog from '../../components/WorkspaceDialog'
import { deleteWorkspace, fetchSettings, fetchWorkspaces, saveSettings, updateWorkspace, type Workspace } from '../../lib/api'
import { accentTextBtnStyle, deleteBtnStyle } from './shared'

export function WorkspacesCard() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [editing, setEditing] = useState<Workspace | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Workspace | null>(null)
  const [deleteFiles, setDeleteFiles] = useState(false)
  const [root, setRoot] = useState('')
  const [resolvedRoot, setResolvedRoot] = useState('')

  const load = useCallback(() => {
    fetchWorkspaces(true).then(d => setWorkspaces(d.workspaces)).catch(() => {})
    fetchSettings().then(s => {
      setRoot(s.workspaces.root)
      setResolvedRoot(s.workspaces.resolved_root)
    }).catch(() => {})
  }, [])
  useEffect(() => { load() }, [load])

  const saveRoot = async () => {
    await saveSettings({
      default_model: '', api_key: '', base_url: '', default_mode: '',
      workspaces_root: root,
    })
    load()
  }

  const setArchived = async (id: string, archived: boolean) => { await updateWorkspace(id, { archived }); load() }
  const confirmDelete = async () => {
    if (!deleteTarget) return
    await deleteWorkspace(deleteTarget.id, deleteFiles && deleteTarget.managed)
    setDeleteTarget(null)
    setDeleteFiles(false)
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
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '0 0 14px' }}>
        <span style={{ fontSize: 12.5, color: 'var(--ink2)', whiteSpace: 'nowrap' }}>Clone workspaces into</span>
        <input
          aria-label="Workspaces root"
          value={root}
          onChange={e => setRoot(e.target.value)}
          onBlur={saveRoot}
          placeholder={resolvedRoot}
          style={{
            flex: 1, minWidth: 0, padding: '5px 8px', borderRadius: 7, fontSize: 11.5,
            fontFamily: 'var(--font-mono)', background: 'var(--card2)', color: 'var(--ink)',
            border: '1px solid var(--line)',
          }}
        />
      </div>
      <div style={{ fontSize: 11, color: 'var(--mut)', margin: '-8px 0 14px' }}>
        Leave blank for the default. Currently{' '}
        <code style={{ fontFamily: 'var(--font-mono)' }}>{resolvedRoot}</code>. Only affects
        workspaces created from here on — existing folders stay where they are.
      </div>

      {active.length === 0 && (
        <div style={{ textAlign: 'center', padding: 12, color: 'var(--mut)', fontSize: 13 }}>No workspaces yet.</div>
      )}
      {active.map(w => (
        <div key={w.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--mut)', minWidth: 80 }}>{w.id}</span>
          <span style={{ fontSize: 13, color: 'var(--ink)', flex: 1 }}>{w.name}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' }}>{w.repository || '—'}</span>
          {/* Worth surfacing: it's the difference between agents
              working on a copy and agents working in your checkout. */}
          {w.managed && <Chip mono soft>managed</Chip>}
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
        message={deleteTarget ? deleteMessage(deleteTarget) : ''}
        confirmLabel="Delete"
        danger
        onConfirm={confirmDelete}
        onCancel={() => { setDeleteTarget(null); setDeleteFiles(false) }}
      >
        {/* Opt-in, and only offered for a managed folder — an
            unmanaged workspace's directory was never ours to remove. */}
        {deleteTarget?.managed && (
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12.5, color: 'var(--err)', marginTop: 10 }}>
            <input type="checkbox" checked={deleteFiles} onChange={e => setDeleteFiles(e.target.checked)} style={{ marginTop: 2 }} />
            <span>
              Also delete the folder and everything in it. Any commits that were never
              pushed are gone for good.
            </span>
          </label>
        )}
      </ConfirmDialog>
    </Card>
  )
}

function deleteMessage(w: Workspace): string {
  const base = `Delete workspace "${w.name}"? Tasks already assigned to it are not deleted.`
  return w.managed
    ? `${base} The folder at ${w.repository} is kept unless you tick the box below.`
    : base
}
