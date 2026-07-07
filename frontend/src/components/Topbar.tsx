import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import type { AgentInfo } from '../lib/api'
import { fetchWorkspaces, type Workspace } from '../lib/api'
import { getActiveWorkspace, setActiveWorkspace } from '../lib/workspace'

interface Props {
  agents: AgentInfo[]
}

function Topbar({ agents }: Props) {
  const totalTokens = agents.reduce((s, a) => s + a.tokens_used, 0)
  const totalCost = agents.reduce((s, a) => s + a.cost_usd, 0)
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [active, setActive] = useState(getActiveWorkspace())

  useEffect(() => {
    fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {})
  }, [])

  const handleWorkspaceChange = (id: string) => {
    setActiveWorkspace(id)
    setActive(id)
    window.location.reload()  // refresh to filter everything
  }

  return (
    <header className="topbar">
      <div className="topbar-brand">⚡ agentjam</div>
      <nav className="topbar-nav">
        <NavLink to="/" end>Overview</NavLink>
        <NavLink to="/board">Board</NavLink>
        <NavLink to="/tasks">List</NavLink>
        <NavLink to="/tools">Tools</NavLink>
      </nav>
      <select
        value={active}
        onChange={e => handleWorkspaceChange(e.target.value)}
        style={{
          marginLeft: 12, padding: '3px 8px', borderRadius: 6, fontSize: 12,
          border: '1px solid var(--border)', background: 'var(--surface-raised)',
          color: 'var(--fg-soft)', outline: 'none', fontFamily: 'inherit', cursor: 'pointer',
          maxWidth: 160,
        }}
      >
        <option value="">All workspaces</option>
        {workspaces.map(w => (
          <option key={w.id} value={w.id}>{w.name}</option>
        ))}
      </select>
      <div className="topbar-stats">
        <span>{agents.length} agent{agents.length !== 1 ? 's' : ''}</span>
        <span>{totalTokens.toLocaleString()} tok</span>
        <span>${totalCost.toFixed(2)}</span>
      </div>
    </header>
  )
}

export default Topbar
