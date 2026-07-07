import { NavLink } from 'react-router-dom'
import type { AgentInfo } from '../lib/api'

interface Props {
  agents: AgentInfo[]
}

function Topbar({ agents }: Props) {
  const totalTokens = agents.reduce((s, a) => s + a.tokens_used, 0)
  const totalCost = agents.reduce((s, a) => s + a.cost_usd, 0)

  return (
    <header className="topbar">
      <div className="topbar-brand">⚡ agentjam</div>
      <nav className="topbar-nav">
        <NavLink to="/" end>Overview</NavLink>
        <NavLink to="/tasks">Tasks</NavLink>
      </nav>
      <div className="topbar-stats">
        <span>{agents.length} agent{agents.length !== 1 ? 's' : ''}</span>
        <span>{totalTokens.toLocaleString()} tok</span>
        <span>${totalCost.toFixed(2)}</span>
      </div>
    </header>
  )
}

export default Topbar
