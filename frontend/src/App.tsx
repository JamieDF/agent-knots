import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import Topbar from './components/Topbar'
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
    <>
      <Topbar agents={agents} />
      <main className="canvas">
        <Outlet />
      </main>
    </>
  )
}

export default App
