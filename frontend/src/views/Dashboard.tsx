import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import AgentCard from '../components/AgentCard'
import SetupWizard from '../components/SetupWizard'
import { fetchAgents, fetchSettings, fetchTasks, createSession, type AgentInfo } from '../lib/api'
import { getActiveWorkspace } from '../lib/workspace'

function Dashboard() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [showWizard, setShowWizard] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [openTasks, setOpenTasks] = useState<{id:string, title:string}[]>([])
  const [showTaskPicker, setShowTaskPicker] = useState(false)
  const workspace = getActiveWorkspace()
  const navigate = useNavigate()

  // Load open tasks for the task picker.
  useEffect(() => {
    fetchTasks({ status: 'open', limit: 10 }).then(d => {
      setOpenTasks(d.tasks.map(t => ({ id: t.id, title: t.title })))
    }).catch(() => {})
  }, [workspace])

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

  const handleInstantStart = async (taskId?: string) => {
    setCreating(true)
    try {
      const session = await createSession({ prompt: '', mode: 'agent', project_id: workspace || undefined, task_id: taskId })
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
                        <div style={{ position: 'relative' }}>               <button className="btn" onClick={() => setShowTaskPicker(!showTaskPicker)} disabled={creating}                 style={{ background: 'var(--info)', color: 'var(--bg)', fontWeight: 600, fontSize: 13 }}>                 {creating ? 'Starting...' : '+ New Session'}               </button>               {showTaskPicker && openTasks.length > 0 && (                 <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: 4, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: 4, minWidth: 240, zIndex: 60, boxShadow: '0 4px 12px rgba(0,0,0,0.3)' }}>                   <div style={{ fontSize: 11, color: 'var(--muted)', padding: '4px 8px' }}>Attach to task (optional)</div>                   <button onClick={() => { handleInstantStart(); setShowTaskPicker(false) }} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 8px', borderRadius: 4, fontSize: 13, color: 'var(--fg-soft)', border: 0, background: 'transparent', cursor: 'pointer', fontFamily: 'inherit' }}>No task — just start</button>                   {openTasks.map(t => (                     <button key={t.id} onClick={() => { handleInstantStart(t.id); setShowTaskPicker(false) }} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 8px', borderRadius: 4, fontSize: 13, color: 'var(--fg)', border: 0, background: 'transparent', cursor: 'pointer', fontFamily: 'inherit' }}>{t.title}</button>                   ))}                 </div>               )}             </div>
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

export default Dashboard
