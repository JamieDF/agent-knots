import { useEffect, useState, useCallback } from 'react'
import AgentCard from '../components/AgentCard'
import SetupWizard from '../components/SetupWizard'
import NewSessionDialog from '../components/NewSessionDialog'
import { fetchAgents, fetchSettings, createSession, type AgentInfo } from '../lib/api'

function Overview() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [configured, setConfigured] = useState<boolean | null>(null) // null = loading
  const [showWizard, setShowWizard] = useState(false)
  const [showNewSession, setShowNewSession] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  const handleWizardComplete = useCallback(() => {
    setConfigured(true)
    setShowWizard(false)
  }, [])

  const handleStartSession = useCallback(async (prompt: string, mode: string) => {
    await createSession({ prompt, mode })
  }, [])

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
              onClick={() => setShowNewSession(true)}
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
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      )}

      {/* New session dialog */}
      {showNewSession && (
        <NewSessionDialog
          onStart={handleStartSession}
          onClose={() => setShowNewSession(false)}
        />
      )}
    </>
  )
}

export default Overview
