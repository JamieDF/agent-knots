import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import AgentCard from '../components/AgentCard'
import SetupWizard from '../components/SetupWizard'
import { fetchAgents, fetchSettings, createSession, type AgentInfo } from '../lib/api'
import { getActiveWorkspace } from '../lib/workspace'

function Overview() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [showWizard, setShowWizard] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const workspace = getActiveWorkspace()
  const navigate = useNavigate()

  // Check if settings are configured.
  useEffect(() => {
    fetchSettings()
      .then(s => {
        setConfigured(s.configured)
        if (!s.configured) setShowWizard(true)
      })
      .catch(() => setConfigured(false))
  }, [])

  // Poll agents.
  useEffect(() => {
    let mounted = true
    const poll = async () => {
      try {
        const data = await fetchAgents()
        if (mounted) {
          // Filter by active workspace.
          const filtered = workspace
            ? data.agents.filter(a => a.project_id === workspace)
            : data.agents
          setAgents(filtered)
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

  const handleWizardComplete = useCallback(() => {
    setConfigured(true)
    setShowWizard(false)
  }, [])

  const handleInstantStart = async () => {
    setCreating(true)
    try {
      const session = await createSession({ prompt: '', mode: 'agent', project_id: workspace || undefined })
      navigate(`/agent/${session.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start')
      setCreating(false)
    }
  }

  // Still loading settings.
  if (configured === null) return null

  return (
    <>
      {/* Setup wizard — first time */}
      {showWizard && <SetupWizard onComplete={handleWizardComplete} />}

      {/* Main overview — only shown after setup */}
      {!showWizard && (
        <div className="overview">
          {/* New session button */}
          <div style={{ gridColumn: '1 / -1', display: 'flex', justifyContent: 'flex-end', marginBottom: 4 }}>
            <button
              className="btn"
              onClick={handleInstantStart}
              disabled={creating}
              style={{
                background: 'var(--info)',
                color: 'var(--bg)',
                fontWeight: 600,
                fontSize: 13,
              }}
            >
              + New Session
            </button>
          </div>

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
              <div className="hint">Click "+ New Session" to start one</div>
            </div>
          )}

          {agents.map(agent => (
            <AgentCard key={agent.id} agent={agent} onDelete={() => setAgents(prev => prev.filter(a => a.id !== agent.id))} />
          ))}
        </div>
      )}
    </>
  )
}

export default Overview
