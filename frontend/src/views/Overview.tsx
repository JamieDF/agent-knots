import { useEffect, useState } from 'react'
import AgentCard from '../components/AgentCard'
import Topbar from '../components/Topbar'
import { fetchAgents, type AgentInfo } from '../lib/api'

function Overview() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true

    const poll = async () => {
      try {
        const data = await fetchAgents()
        if (mounted) {
          setAgents(data.agents)
          setError(null)
        }
      } catch (err) {
        if (mounted) setError(err instanceof Error ? err.message : 'Connection failed')
      }
    }

    poll()
    const interval = setInterval(poll, 2000)
    return () => { mounted = false; clearInterval(interval) }
  }, [])

  return (
    <>
      <Topbar agents={agents} />
      <div className="overview">
        {error && (
          <div className="overview-empty">
            <div className="icon">⚠️</div>
            <div className="title">Connection lost</div>
            <div className="hint">{error} — retrying…</div>
          </div>
        )}
        {!error && agents.length === 0 && (
          <div className="overview-empty">
            <div className="icon">⚡</div>
            <div className="title">No agents running</div>
            <div className="hint">agentjam session start --detach</div>
          </div>
        )}
        {agents.map(agent => (
          <AgentCard key={agent.id} agent={agent} />
        ))}
      </div>
    </>
  )
}

export default Overview
