import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import type { AgentInfo } from '../lib/api'
import { useWorkspaceScope } from '../lib/workspaceContext'
import { useTheme } from '../theme/ThemeContext'
import NewSessionDialog from './NewSessionDialog'
import NotificationBell from './NotificationBell'
import WorkspaceSwitcher from './WorkspaceSwitcher'

interface Props {
  agents: AgentInfo[]
}

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/tasks', label: 'Tasks', end: false },
  { to: '/review', label: 'Review', end: false },
  { to: '/workflows', label: 'Workflows', end: false },
  { to: '/settings', label: 'Settings', end: false },
]

/** Floating top-bar pill nav: Dashboard · Tasks · Review · Workflows ·
 * Settings, plus workspace scope, stats, notifications, theme toggle,
 * + New session. Vault was originally its own top-nav screen per
 * design_handoff_atelier_cockpit/README.md, but per usage feedback it's
 * just more config — folded into a Settings section instead. */
function Topbar({ agents }: Props) {
  const totalTokens = agents.reduce((s, a) => s + a.tokens_used, 0)
  const { workspace } = useWorkspaceScope()
  const { theme, toggleTheme } = useTheme()
  const [showNewSession, setShowNewSession] = useState(false)

  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 16px',
        margin: 10,
        borderRadius: 12,
        background: 'var(--card)',
        border: '1px solid var(--line)',
        boxShadow: 'var(--shadow)',
        flexShrink: 0,
      }}
    >
      <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--ink)', paddingRight: 4 }}>⚡ agent-knots</div>

      <nav style={{ display: 'flex', gap: 2 }}>
        {NAV_ITEMS.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            style={({ isActive }) => ({
              padding: '5px 12px',
              borderRadius: 8,
              fontSize: 13,
              fontWeight: 500,
              textDecoration: 'none',
              color: isActive ? 'var(--ink)' : 'var(--ink2)',
              background: isActive ? 'var(--card2)' : 'transparent',
            })}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <WorkspaceSwitcher />

      <div
        style={{
          marginLeft: 8, padding: '4px 10px', borderRadius: 8,
          background: 'var(--card2)', fontSize: 11.5, fontFamily: 'var(--font-mono)',
          color: 'var(--ink2)', whiteSpace: 'nowrap',
        }}
      >
        {agents.length} agent{agents.length !== 1 ? 's' : ''} · {formatTokens(totalTokens)} tok
      </div>

      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
        <NotificationBell />
        <button
          onClick={toggleTheme}
          title="Toggle theme"
          style={{ fontSize: 15, padding: '4px 6px', borderRadius: 8, color: 'var(--ink2)' }}
        >
          {theme === 'dark' ? '☀' : '☾'}
        </button>
        <button
          onClick={() => setShowNewSession(true)}
          style={{
            padding: '6px 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600,
            background: 'var(--acc)', color: 'var(--acc-ink)',
          }}
        >
          + New session
        </button>
      </div>

      <NewSessionDialog open={showNewSession} onClose={() => setShowNewSession(false)} defaultWorkspace={workspace} />
    </header>
  )
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}

export default Topbar
