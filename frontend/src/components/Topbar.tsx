import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
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
  const [tasksOpen, setTasksOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {})
  }, [])

  // Close dropdown on nav.
  useEffect(() => { setTasksOpen(false) }, [location])

  const handleWorkspaceChange = (id: string) => {
    setActiveWorkspace(id)
    setActive(id)
    window.location.reload()
  }

  const isTasksActive = location.pathname.startsWith('/board') || location.pathname.startsWith('/tasks')

  return (
    <header className="topbar">
      <div className="topbar-brand">⚡ agent-knots</div>
      <nav className="topbar-nav">
        <NavLink to="/" end>Overview</NavLink>

        {/* Tasks dropdown */}
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setTasksOpen(!tasksOpen)}
            style={{
              color: isTasksActive ? 'var(--fg)' : 'var(--fg-soft)',
              textDecoration: 'none', padding: '4px 12px', borderRadius: 6, fontSize: 13,
              fontWeight: 500, background: isTasksActive ? 'var(--surface-raised)' : 'transparent',
              border: 0, cursor: 'pointer', fontFamily: 'inherit',
              display: 'flex', alignItems: 'center', gap: 4,
            }}
            onBlur={() => setTimeout(() => setTasksOpen(false), 150)}
          >
            Tasks ▾
          </button>
          {tasksOpen && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, marginTop: 4,
              background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: 8, padding: 4, minWidth: 100, zIndex: 60,
              boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            }}>
              <NavLink to="/board" style={dropdownLink}>Board</NavLink>
              <NavLink to="/tasks" style={dropdownLink}>List</NavLink>
            </div>
          )}
        </div>

        <NavLink to="/settings">Settings</NavLink>
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

const dropdownLink: React.CSSProperties = {
  display: 'block', padding: '6px 12px', borderRadius: 4, fontSize: 13,
  color: 'var(--fg-soft)', textDecoration: 'none',
}

export default Topbar
