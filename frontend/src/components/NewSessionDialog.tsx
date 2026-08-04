import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchTasks, fetchWorkspaces, fetchWorkspace, createSession, type TaskSummary, type Workspace } from '../lib/api'
import { Dialog, Field, inputStyle } from './primitives'

interface Props {
  open: boolean
  onClose: () => void
  defaultWorkspace?: string
}

/** "+ New session" dialog — card-picker redesign. Workspace at the top
 * drives the Location readout (the workspace's default repo/path).
 * Two selectable mode cards (Autonomous / Guided) replace the old
 * "Mode" dropdown. Single "Create" button replaces the old headless/
 * watch split. */
function NewSessionDialog({ open, onClose, defaultWorkspace }: Props) {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [taskId, setTaskId] = useState('')
  const [prompt, setPrompt] = useState('')
  const [mode, setMode] = useState('assistant')
  const [workspace, setWorkspace] = useState(defaultWorkspace || '')
  const [location, setLocation] = useState('')
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    if (!open) return
    fetchTasks({ status: 'open', limit: 20 }).then(d => setTasks(d.tasks)).catch(() => {})
    fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {})
    setTaskId(''); setPrompt(''); setMode('assistant'); setError('')
    const ws = defaultWorkspace || ''
    setWorkspace(ws)
    if (ws) {
      fetchWorkspace(ws).then(w => setLocation(w.repository)).catch(() => setLocation(''))
    } else {
      setLocation('')
    }
  }, [open, defaultWorkspace])

  const handleWorkspaceChange = async (wsId: string) => {
    setWorkspace(wsId)
    if (wsId) {
      try {
        const w = await fetchWorkspace(wsId)
        setLocation(w.repository)
      } catch { setLocation('') }
    } else {
      setLocation('')
    }
  }

  // Attaching a task implies the agent should self-direct — auto-switch
  // to Autonomous. Clearing the task resets back to the safe default (Guided).
  useEffect(() => {
    if (taskId) setMode('agent'); else setMode('assistant')
  }, [taskId])

  const handleCreate = async () => {
    setStarting(true); setError('')
    try {
      const session = await createSession({
        prompt, mode,
        project_id: workspace || undefined,
        task_id: taskId || undefined,
      })
      onClose()
      // Autonomous = background start: the agent self-directs from its
      // task, so there's nothing to watch in real time — stay on the
      // dashboard and let it show up as a running agent card. Guided =
      // opens the thread, since you're the one driving it.
      if (mode !== 'agent') navigate(`/agent/${session.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start')
    } finally {
      setStarting(false)
    }
  }

  const cardStyle = (selected: boolean): React.CSSProperties => ({
    padding: '16px 14px', borderRadius: 12, cursor: 'pointer', textAlign: 'left',
    fontFamily: 'inherit', border: selected ? '2px solid var(--acc)' : '2px solid var(--line)',
    background: selected ? '#f8f6ff' : 'var(--card2)',
  })

  const iconBox = (selected: boolean): React.CSSProperties => ({
    width: 36, height: 36, borderRadius: 10, display: 'flex', alignItems: 'center',
    justifyContent: 'center', fontSize: 16, marginBottom: 8,
    background: selected ? '#f0ecff' : '#f0f2f5',
    color: selected ? 'var(--acc)' : 'var(--ink2)',
  })

  return (
    <Dialog open={open} onClose={onClose} width={500}>
      <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 14 }}>New session</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

        <Field label="Workspace">
          <select aria-label="Workspace" value={workspace} onChange={e => handleWorkspaceChange(e.target.value)} style={inputStyle}>
            <option value="">None</option>
            {workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </Field>

        {location && (
          <Field label="Location">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 8, background: 'var(--card2)', border: '1px solid var(--line2)' }}>
              <span style={{ color: 'var(--mut)', fontSize: 12, flexShrink: 0 }}>📁</span>
              <span style={{ fontSize: 13, color: 'var(--ink)', fontFamily: 'var(--font-mono)' }}>{location}</span>
            </div>
          </Field>
        )}

        <Field label="Attach to task">
          <select aria-label="Attach to task" value={taskId} onChange={e => setTaskId(e.target.value)} style={inputStyle}>
            <option value="">No task — just start</option>
            {tasks.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
          </select>
          {taskId && <span style={{ fontSize: 11, color: 'var(--mut)' }}>Prior progress is injected as memory.</span>}
        </Field>

        <Field label="Prompt">
          <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={2} placeholder={taskId ? "Optional — the task description is the starting point" : "What should the agent do?"} style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
        </Field>

        <Field label="How should the agent work?">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <button type="button" onClick={() => setMode('agent')} style={cardStyle(mode === 'agent')}>
              <div style={iconBox(mode === 'agent')}>▶</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: mode === 'agent' ? 'var(--acc)' : 'var(--ink)', marginBottom: 3 }}>Autonomous</div>
              <div style={{ fontSize: 11, color: 'var(--ink2)', lineHeight: 1.4 }}>Self-directs through the task. Pause anytime from the thread.</div>
            </button>
            <button type="button" onClick={() => setMode('assistant')} style={cardStyle(mode === 'assistant')}>
              <div style={iconBox(mode === 'assistant')}>⏸</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: mode === 'assistant' ? 'var(--acc)' : 'var(--ink)', marginBottom: 3 }}>Guided</div>
              <div style={{ fontSize: 11, color: 'var(--ink2)', lineHeight: 1.4 }}>Waits for your input after each action. You drive, it executes.</div>
            </button>
          </div>
        </Field>

        {error && <div style={{ color: 'var(--err)', fontSize: 13 }}>{error}</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={onClose} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
          <button
            onClick={handleCreate}
            disabled={starting}
            style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: starting ? 0.6 : 1 }}
          >
            {starting ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}

export default NewSessionDialog
