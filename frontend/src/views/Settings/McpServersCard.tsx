import { useCallback, useEffect, useState } from 'react'
import { Card, SectionLabel, Toggle, inputStyle } from '../../components/primitives'
import { addMcpServer, deleteMcpServer, fetchMcpServers, toggleMcpServer, type McpServerInfo } from '../../lib/api'
import { accentTextBtnStyle, deleteBtnStyle } from './shared'

export function McpServersCard() {
  const [servers, setServers] = useState<McpServerInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')

  const load = useCallback(() => { fetchMcpServers().then(d => setServers(d.servers)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  const handleAdd = async () => {
    if (!name.trim()) return
    await addMcpServer({ name: name.trim(), url })
    setName(''); setUrl(''); setShowAdd(false)
    load()
  }

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>MCP servers</SectionLabel>
      </div>
      {servers.length === 0 && !showAdd && (
        <div style={{ textAlign: 'center', padding: 12, color: 'var(--mut)', fontSize: 13 }}>No MCP servers configured.</div>
      )}
      {servers.map(s => (
        <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', flex: 1 }}>{s.name}</span>
          <span style={{ fontSize: 11, color: 'var(--mut)' }}>{s.tool_count} tools exposed</span>
          <Toggle checked={s.enabled} onChange={async checked => { await toggleMcpServer(s.name, checked); load() }} />
          <button onClick={async () => { await deleteMcpServer(s.name); load() }} style={deleteBtnStyle}>✕</button>
        </div>
      ))}
      {showAdd ? (
        <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
          <input aria-label="MCP server name" value={name} onChange={e => setName(e.target.value)} placeholder="filesystem" style={{ ...inputStyle, flex: 1 }} />
          <input aria-label="MCP server URL" value={url} onChange={e => setUrl(e.target.value)} placeholder="stdio://..." style={{ ...inputStyle, flex: 1 }} />
          <button onClick={handleAdd} style={{ fontSize: 12, fontWeight: 600, color: 'var(--acc-ink)', background: 'var(--acc)', padding: '6px 12px', borderRadius: 8, whiteSpace: 'nowrap' }}>Add</button>
        </div>
      ) : (
        <button onClick={() => setShowAdd(true)} style={accentTextBtnStyle({ marginTop: 10 })}>+ Add MCP server</button>
      )}
    </Card>
  )
}
