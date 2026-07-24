import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchTasks, fetchWorkspaces, createSession, type TaskSummary, type Workspace } from '../lib/api'
import { Dialog, Field, inputStyle } from './primitives'

interface Props {
  open: boolean
  onClose: () => void
  defaultWorkspace?: string
}

/** "+ New session" dialog per design_handoff_atelier_cockpit/README.md
 * §11 — attach-to-task select (prior progress is injected as memory),
 * prompt, mode/workspace selects. Replaces the old ad-hoc inline
 * task-picker on Dashboard and wires up Topbar's previously-disabled
 * placeholder button. */
function NewSessionDialog({ open, onClose, defaultWorkspace }: Props) {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [taskId, setTaskId] = useState('')
  const [prompt, setPrompt] = useState('')
  const [mode, setMode] = useState('agent')
  const [workspace, setWorkspace] = useState(defaultWorkspace || '')
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    if (!open) return
    fetchTasks({ status: 'open', limit: 20 }).then(d => setTasks(d.tasks)).catch(() => {})
    fetchWorkspaces().then(d => setWorkspaces(d.workspaces)).catch(() => {})
    setTaskId(''); setPrompt(''); setMode('agent'); setWorkspace(defaultWorkspace || ''); setError('')
  }, [open, defaultWorkspace])

  const handleStart = async (headless: boolean) => {
    setStarting(true); setError('')
    try {
      const session = await createSession({
        prompt, mode,
        project_id: workspace || undefined,
        task_id: taskId || undefined,
      })
      onClose()
      if (!headless) navigate(`/agent/${session.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start')
    } finally {
      setStarting(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} width={480}>
      <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 14 }}>New session</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Attach to task">
          <select aria-label="Attach to task" value={taskId} onChange={e => setTaskId(e.target.value)} style={inputStyle}>
            <option value="">No task — just start</option>
            {tasks.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
          </select>
          {taskId && <span style={{ fontSize: 11, color: 'var(--mut)' }}>Prior progress is injected as memory.</span>}
        </Field>

        <Field label="Prompt">
          <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={3} placeholder="What should the agent do?" style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
        </Field>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <Field label="Mode">
            <select aria-label="Mode" value={mode} onChange={e => setMode(e.target.value)} style={inputStyle}>
              <option value="agent">Agent (autonomous)</option>
              <option value="assistant">Assistant (interactive)</option>
            </select>
          </Field>
          <Field label="Workspace">
            <select aria-label="Workspace" value={workspace} onChange={e => setWorkspace(e.target.value)} style={inputStyle}>
              <option value="">None</option>
              {workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </Field>
        </div>

        {error && <div style={{ color: 'var(--err)', fontSize: 13 }}>{error}</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={onClose} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
          <button
            onClick={() => handleStart(true)}
            disabled={starting}
            title="Start in the background — open the thread later"
            style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)', opacity: starting ? 0.6 : 1 }}
          >
            ⏵ Start headless
          </button>
          <button
            onClick={() => handleStart(false)}
            disabled={starting}
            title="Start and open the thread now"
            style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: starting ? 0.6 : 1 }}
          >
            {starting ? 'Starting…' : '▶ Start (watch)'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}

export default NewSessionDialog
