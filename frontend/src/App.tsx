import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import Topbar from './components/Topbar'
import { ThemeProvider } from './theme/ThemeContext'
import { AccessibilityProvider } from './theme/AccessibilityContext'
import { WorkspaceProvider } from './lib/workspaceContext'
import { fetchAgents, type AgentInfo } from './lib/api'
import './App.css'

function App() {
  const [agents, setAgents] = useState<AgentInfo[]>([])

  useEffect(() => {
    let mounted = true
    const poll = async () => {
      try {
        const data = await fetchAgents()
        if (mounted) setAgents(data.agents)
      } catch { /* ignore */ }
    }
    poll()
    const interval = setInterval(poll, 3000)
    return () => { mounted = false; clearInterval(interval) }
  }, [])

  return (
    <ThemeProvider>
      <AccessibilityProvider>
        <WorkspaceProvider>
          <Topbar agents={agents} />
          <main className="canvas">
            <Outlet />
          </main>
        </WorkspaceProvider>
      </AccessibilityProvider>
    </ThemeProvider>
  )
}

export default App
