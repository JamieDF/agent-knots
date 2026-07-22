import { useEffect, useState } from 'react'
import { Dialog } from './primitives'
import { fetchFsBrowse, type FsEntry } from '../lib/api'

interface Props {
  open: boolean
  initialPath?: string
  onClose: () => void
  onSelect: (path: string) => void
}

/** Server-assisted directory browser — a native OS file dialog can't
 * hand back an absolute path a backend process can use, so this walks
 * the filesystem the server itself can see (this is a local-first,
 * single-user app; the server already runs on the same machine). */
function FolderPicker({ open, initialPath, onClose, onSelect }: Props) {
  const [path, setPath] = useState('')
  const [parent, setParent] = useState<string | null>(null)
  const [entries, setEntries] = useState<FsEntry[]>([])
  const [error, setError] = useState('')

  const load = (target?: string) => {
    fetchFsBrowse(target).then(d => {
      setPath(d.path)
      setParent(d.parent)
      setEntries(d.entries)
      setError('')
    }).catch(e => setError(e instanceof Error ? e.message : 'Failed to browse'))
  }

  useEffect(() => {
    if (open) load(initialPath)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  if (!open) return null

  return (
    <Dialog open onClose={onClose} width={460}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>Choose a folder</div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        <input
          aria-label="Folder path"
          value={path}
          onChange={e => setPath(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') load(path) }}
          style={inputStyle}
        />
        <button onClick={() => load(path)} style={goBtnStyle}>Go</button>
      </div>

      {error && <div style={{ fontSize: 11.5, color: 'var(--err)', marginBottom: 8 }}>{error}</div>}

      <div style={{ maxHeight: 280, overflowY: 'auto', border: '1px solid var(--line)', borderRadius: 8 }}>
        {parent !== null && (
          <div onClick={() => load(parent)} style={rowStyle}>
            <span style={{ color: 'var(--mut)' }}>⬆</span>
            <span style={{ color: 'var(--ink2)' }}>..</span>
          </div>
        )}
        {entries.length === 0 && parent === null && (
          <div style={{ padding: 14, textAlign: 'center', fontSize: 12.5, color: 'var(--mut)' }}>No subfolders here.</div>
        )}
        {entries.map(e => (
          <div key={e.path} onClick={() => load(e.path)} style={rowStyle}>
            <span>📁</span>
            <span style={{ flex: 1, color: 'var(--ink)' }}>{e.name}</span>
            {e.is_git && <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--acc)' }}>git</span>}
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}>
        <button onClick={onClose} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
        <button onClick={() => onSelect(path)} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 700, background: 'var(--acc)', color: 'var(--acc-ink)' }}>
          Use this folder
        </button>
      </div>
    </Dialog>
  )
}

const inputStyle: React.CSSProperties = {
  flex: 1, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line2)',
  background: 'var(--card2)', color: 'var(--ink)', fontSize: 12.5, outline: 'none',
  fontFamily: 'var(--font-mono)',
}

const goBtnStyle: React.CSSProperties = {
  padding: '0 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)',
}

const rowStyle: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', fontSize: 12.5,
  borderBottom: '1px solid var(--line)', cursor: 'pointer',
}

export default FolderPicker
