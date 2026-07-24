import { useState } from 'react'
import { fetchAgentFile } from '../../lib/api'
import Markdown from '../../components/Markdown'
import { PanelEmptyState, PanelHeader } from './shared'
import type { FileChange } from './types'

interface FileFetch {
  status: 'loading' | 'ready' | 'error'
  content?: string
  truncated?: boolean
  error?: string
}

const MARKDOWN_EXT = /\.(md|markdown)$/i

export function FilesPanel({ files, agentId }: { files: FileChange[]; agentId?: string }) {
  const colors: Record<string, string> = { edit: 'var(--warn-ink)', write: 'var(--ok)', read: 'var(--acc)' }
  const letters: Record<string, string> = { edit: 'M', write: 'A', read: 'R' }
  const [expanded, setExpanded] = useState<string | null>(null)
  const [cache, setCache] = useState<Record<string, FileFetch>>({})

  const toggle = (path: string) => {
    if (expanded === path) { setExpanded(null); return }
    setExpanded(path)
    if (!agentId || cache[path]) return
    setCache(prev => ({ ...prev, [path]: { status: 'loading' } }))
    fetchAgentFile(agentId, path)
      .then(res => setCache(prev => ({ ...prev, [path]: { status: 'ready', content: res.content, truncated: res.truncated } })))
      .catch(e => setCache(prev => ({ ...prev, [path]: { status: 'error', error: e instanceof Error ? e.message : 'Failed to load' } })))
  }

  return (
    <div>
      <PanelHeader>{files.length} file{files.length !== 1 ? 's' : ''} touched</PanelHeader>
      {files.length === 0 && <PanelEmptyState>Files the agent reads or edits will appear here.</PanelEmptyState>}
      {files.map((f, i) => {
        const isOpen = expanded === f.path
        const entry = cache[f.path]
        return (
          <div key={i} style={{ borderBottom: '1px solid var(--line)' }}>
            <div
              onClick={() => toggle(f.path)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', fontSize: 11, cursor: 'pointer' }}
            >
              <span style={{ width: 16, height: 16, borderRadius: 3, display: 'grid', placeItems: 'center', fontSize: 9, fontWeight: 700, fontFamily: 'var(--font-mono)', color: colors[f.action] || 'var(--mut)', background: 'var(--card2)' }}>{letters[f.action] || '·'}</span>
              <span style={{ flex: 1, fontFamily: 'var(--font-mono)', color: 'var(--ink2)', wordBreak: 'break-all' }}>{f.path}</span>
              <span style={{ fontSize: 9, color: 'var(--mut)' }}>{isOpen ? '▾' : '▸'}</span>
            </div>
            {isOpen && (
              <div style={{ padding: '0 10px 10px', background: 'var(--card2)' }}>
                {(!entry || entry.status === 'loading') && <div style={{ fontSize: 11, color: 'var(--mut)', padding: '8px 0' }}>Loading…</div>}
                {entry?.status === 'error' && <div style={{ fontSize: 11, color: 'var(--err)', padding: '8px 0' }}>{entry.error}</div>}
                {entry?.status === 'ready' && (
                  <div style={{ maxHeight: 320, overflowY: 'auto', border: '1px solid var(--line)', borderRadius: 6, background: 'var(--card)', padding: MARKDOWN_EXT.test(f.path) ? '8px 10px' : 0 }}>
                    {entry.truncated && <div style={{ fontSize: 10, color: 'var(--warn-ink)', padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>Truncated — showing the first part of a large file.</div>}
                    {MARKDOWN_EXT.test(f.path) ? (
                      <Markdown fontSize={11.5}>{entry.content || ''}</Markdown>
                    ) : (
                      <pre style={{ margin: 0, padding: '8px 10px', fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--ink2)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{entry.content}</pre>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
