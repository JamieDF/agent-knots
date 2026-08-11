import { useEffect, useState } from 'react'
import { Dialog, Field, inputStyle } from './primitives'
import FolderPicker from './FolderPicker'
import { createWorkspace, updateWorkspace, fetchGitInfo, fetchSettings, type Workspace, type ProviderInfo } from '../lib/api'

interface Props {
  workspace: Workspace | null
  onClose: () => void
  onSaved: () => void
}

/** Create/edit workspace dialog. No id field — the backend slugifies
 * one from the name.
 *
 * New workspaces are "managed" by default: agent-knots clones the repo
 * into a folder it owns under the workspaces root, and agents work
 * there rather than in the checkout you have open in your editor. The
 * alternative — pointing straight at a folder you already have — is
 * still available, and is what every workspace created before managed
 * clones existed still does.
 *
 * Editing never offers the choice: a workspace can't be converted
 * between modes, since that would mean moving or abandoning real code
 * on disk.
 *
 * Shared by the Dashboard's empty-state CTA and the Settings
 * Workspaces card, so both stay in sync automatically. */
function WorkspaceDialog({ workspace, onClose, onSaved }: Props) {
  const [name, setName] = useState(workspace?.name || '')
  const [repository, setRepository] = useState(workspace?.repository || '')
  const [managed, setManaged] = useState(workspace ? workspace.managed : true)
  const [initGit, setInitGit] = useState(false)
  const [runtime, setRuntime] = useState(workspace?.runtime || '')
  const [provider, setProvider] = useState(workspace?.provider || '')
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [showPicker, setShowPicker] = useState(false)
  const [githubUrl, setGithubUrl] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // The clone runs inside the create request, so "Saving…" would
  // undersell a wait that can run to minutes on a big repo.
  const cloning = saving && !workspace && managed && !!repository.trim()

  useEffect(() => {
    fetchSettings().then(s => setProviders(s.providers)).catch(() => {})
  }, [])

  // Only meaningful for a path on disk — there's nothing local to
  // inspect for a URL we haven't cloned yet.
  useEffect(() => {
    const value = repository.trim()
    if (!value || isRemoteUrl(value)) { setGithubUrl(null); return }
    let cancelled = false
    fetchGitInfo(value).then(info => {
      if (!cancelled) setGithubUrl(info.github_url)
    }).catch(() => { if (!cancelled) setGithubUrl(null) })
    return () => { cancelled = true }
  }, [repository])

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      if (workspace) {
        // repository is omitted for a managed workspace — the backend
        // rejects repointing one, and there's nothing to change.
        await updateWorkspace(workspace.id, {
          name, runtime, provider, ...(workspace.managed ? {} : { repository }),
        })
      } else {
        if (!name.trim()) return
        await createWorkspace({
          name: name.trim(), repository, runtime, provider,
          managed, init_git: managed && !repository.trim() && initGit,
        })
      }
      onSaved()
    } catch (e) {
      // A clone can fail for entirely ordinary reasons — bad URL, no
      // auth, not a repo — and the user needs git's own words, not a
      // dialog that silently stays open.
      setError(e instanceof Error ? e.message : 'Could not create workspace')
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
        {!workspace && (
          <Field label="Where the agents work">
            <div style={{ display: 'flex', gap: 6 }}>
              <ModeButton
                active={managed} onClick={() => setManaged(true)}
                title="Managed copy"
                subtitle="agent-knots clones it. Your own checkout is never touched."
              />
              <ModeButton
                active={!managed} onClick={() => setManaged(false)}
                title="This folder"
                subtitle="Agents edit the folder directly, as you have it now."
              />
            </div>
          </Field>
        )}

        <Field label={managed && !workspace ? 'Repository URL or folder' : 'Folder'}>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              aria-label="Repository"
              value={repository}
              onChange={e => setRepository(e.target.value)}
              disabled={!!workspace?.managed}
              placeholder={managed && !workspace ? 'https://github.com/you/repo (optional)' : '/path/to/project (optional)'}
              style={{
                ...inputStyle, flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12,
                opacity: workspace?.managed ? 0.6 : 1,
              }}
            />
            {!workspace?.managed && (
              <button onClick={() => setShowPicker(true)} style={browseBtnStyle}>📁 Browse…</button>
            )}
          </div>
          {githubUrl && (
            <a href={githubUrl} target="_blank" rel="noreferrer" style={{ fontSize: 11.5, color: 'var(--acc)', marginTop: 2 }}>
              🔗 {githubUrl.replace('https://', '')}
            </a>
          )}
          {workspace?.managed && (
            <div style={hintStyle}>
              Managed by agent-knots — this folder can't be repointed.
            </div>
          )}
          {!workspace && managed && (
            <div style={hintStyle}>
              {repository.trim() ? 'Cloned to' : 'Created at'}{' '}
              <code style={{ fontFamily: 'var(--font-mono)' }}>
                …/workspaces/{destinationName(repository, name)}/
              </code>
            </div>
          )}
        </Field>

        {/* Only for a managed workspace with nothing to clone: an empty
            folder is useful for writing, research or planning, where
            git buys nothing. Review works either way. */}
        {!workspace && managed && !repository.trim() && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: 'var(--ink2)' }}>
            <input type="checkbox" checked={initGit} onChange={e => setInitGit(e.target.checked)} />
            Initialise it as a git repository
          </label>
        )}
        <Field label="Runtime">
          {/* Subprocess used to be a second option here — removed along
              with SubprocessRuntime, which never actually worked.
              In-process is the only real runtime today. */}
          <select aria-label="Runtime" value={runtime} onChange={e => setRuntime(e.target.value)} style={inputStyle}>
            <option value="">(use global)</option>
            <option value="inprocess">In-process</option>
          </select>
        </Field>
        <Field label="Provider">
          <select aria-label="Provider" value={provider} onChange={e => setProvider(e.target.value)} style={inputStyle}>
            <option value="">(use global default)</option>
            {providers.map(p => <option key={p.name} value={p.name}>{p.name} ({p.model})</option>)}
          </select>
        </Field>
        {error && (
          <div style={{ fontSize: 12, color: 'var(--err)', border: '1px solid var(--err)', padding: '8px 10px', borderRadius: 8, wordBreak: 'break-word' }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={onClose} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
          <button onClick={handleSave} disabled={saving || !name.trim()} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 700, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: saving || !name.trim() ? 0.6 : 1 }}>
            {saving ? (cloning ? 'Cloning…' : 'Saving…') : workspace ? 'Save' : 'Create'}
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

/** Mirrors gitutil.is_remote_url — only used to decide whether the
 * local git-info lookup is worth attempting. */
function isRemoteUrl(source: string): boolean {
  return /^(https?:\/\/|ssh:\/\/|git:\/\/|git@)/.test(source.trim())
}

/** Preview of the folder name a managed workspace will land in.
 * Mirrors gitutil.repo_name_from_source; only a hint, since the
 * authoritative path (including any -2 dedupe suffix) comes back in the
 * create response. */
function destinationName(repository: string, name: string): string {
  const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'workspace'
  const source = repository.trim().replace(/\/+$/, '')
  if (!source) return slug
  const segment = (source.split('/').pop() || '').split(':').pop() || ''
  const cleaned = segment.replace(/\.git$/, '').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '')
  return cleaned || slug
}

function ModeButton({ active, onClick, title, subtitle }: {
  active: boolean; onClick: () => void; title: string; subtitle: string
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      style={{
        flex: 1, textAlign: 'left', padding: '8px 10px', borderRadius: 8,
        background: active ? 'var(--acc-soft)' : 'var(--card2)',
        border: `1px solid ${active ? 'var(--acc)' : 'transparent'}`,
      }}
    >
      <div style={{ fontSize: 12.5, fontWeight: 700, color: active ? 'var(--acc)' : 'var(--ink)' }}>{title}</div>
      <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 2, lineHeight: 1.35 }}>{subtitle}</div>
    </button>
  )
}

const hintStyle: React.CSSProperties = {
  fontSize: 11.5, color: 'var(--mut)', marginTop: 3, wordBreak: 'break-all',
}

const browseBtnStyle: React.CSSProperties = {
  padding: '0 12px', borderRadius: 8, fontSize: 12, fontWeight: 600, color: 'var(--ink2)',
  background: 'var(--card2)', whiteSpace: 'nowrap',
}

export default WorkspaceDialog
