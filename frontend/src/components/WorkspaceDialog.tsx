import { useEffect, useState } from 'react'
import { Dialog } from './primitives'
import FolderPicker from './FolderPicker'
import { createWorkspace, updateWorkspace, fetchGitInfo, type Workspace } from '../lib/api'

interface Props {
  workspace: Workspace | null
  onClose: () => void
  onSaved: () => void
}

/** Create/edit workspace dialog. No id field — the backend slugifies
 * one from the name. "Repository" is chosen via a server-assisted
 * folder browser rather than typed blind, and shows a GitHub link
 * as soon as the chosen folder turns out to be a repo with a GitHub
 * remote. Shared by the Dashboard's empty-state CTA and the Settings
 * Workspaces card, so both stay in sync automatically. */
function WorkspaceDialog({ workspace, onClose, onSaved }: Props) {
  const [name, setName] = useState(workspace?.name || '')
  const [repository, setRepository] = useState(workspace?.repository || '')
  const [runtime, setRuntime] = useState(workspace?.runtime || '')
  const [showPicker, setShowPicker] = useState(false)
  const [githubUrl, setGithubUrl] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!repository.trim()) { setGithubUrl(null); return }
    let cancelled = false
    fetchGitInfo(repository.trim()).then(info => {
      if (!cancelled) setGithubUrl(info.github_url)
    }).catch(() => { if (!cancelled) setGithubUrl(null) })
    return () => { cancelled = true }
  }, [repository])

  const handleSave = async () => {
    setSaving(true)
    try {
      if (workspace) {
        await updateWorkspace(workspace.id, { name, repository, runtime })
      } else {
        if (!name.trim()) return
        await createWorkspace({ name: name.trim(), repository, runtime })
      }
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onClose={onClose} width={440}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>{workspace ? `Edit ${workspace.name}` : '+ New workspace'}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Name">
          <input aria-label="Workspace name" value={name} onChange={e => setName(e.target.value)} placeholder="My project" style={inputStyle} autoFocus />
        </Field>
        <Field label="Folder">
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              aria-label="Repository"
              value={repository}
              onChange={e => setRepository(e.target.value)}
              placeholder="/path/to/project (optional)"
              style={{ ...inputStyle, flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12 }}
            />
            <button onClick={() => setShowPicker(true)} style={browseBtnStyle}>📁 Browse…</button>
          </div>
          {githubUrl && (
            <a href={githubUrl} target="_blank" rel="noreferrer" style={{ fontSize: 11.5, color: 'var(--acc)', marginTop: 2 }}>
              🔗 {githubUrl.replace('https://', '')}
            </a>
          )}
        </Field>
        <Field label="Runtime">
          {/* Subprocess used to be a second option here — removed along
              with SubprocessRuntime, which never actually worked (see
              docs/RETRO.md). In-process is the only real runtime today. */}
          <select aria-label="Runtime" value={runtime} onChange={e => setRuntime(e.target.value)} style={inputStyle}>
            <option value="">(use global)</option>
            <option value="inprocess">In-process</option>
          </select>
        </Field>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={onClose} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
          <button onClick={handleSave} disabled={saving || !name.trim()} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 700, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: saving || !name.trim() ? 0.6 : 1 }}>
            {saving ? 'Saving…' : workspace ? 'Save' : 'Create'}
          </button>
        </div>
      </div>

      <FolderPicker
        open={showPicker}
        initialPath={repository || undefined}
        onClose={() => setShowPicker(false)}
        onSelect={p => { setRepository(p); setShowPicker(false) }}
      />
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <label style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--mut)' }}>{label}</label>
      {children}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line2)',
  background: 'var(--card2)', color: 'var(--ink)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
}

const browseBtnStyle: React.CSSProperties = {
  padding: '0 12px', borderRadius: 8, fontSize: 12, fontWeight: 600, color: 'var(--ink2)',
  background: 'var(--card2)', whiteSpace: 'nowrap',
}

export default WorkspaceDialog
