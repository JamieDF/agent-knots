import { useEffect, useMemo, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import SetupWizard from '../components/SetupWizard'
import NewSessionDialog from '../components/NewSessionDialog'
import WorkspaceDialog from '../components/WorkspaceDialog'
import DeskLayout from '../components/DeskLayout'
import { Card, Chip, Toggle } from '../components/primitives'
import { priorityColor } from '../lib/priorityColors'
import { useStages, enabledStages, stageForStatus, type Stage } from '../lib/stages'
import { useWorkspaceScope } from '../lib/workspaceContext'
import {
  fetchAgents, fetchSettings, fetchTasks, fetchTask, fetchWorkspaces, deleteAgent, sendMessage,
  updateTask, createSession, updateWorkspace,
  type AgentInfo, type TaskSummary, type Workspace,
} from '../lib/api'

const UNASSIGNED = '__unassigned__'

function Dashboard() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [showWizard, setShowWizard] = useState(false)
  const [showNewSession, setShowNewSession] = useState(false)
  const [showNewWorkspace, setShowNewWorkspace] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { workspace: scope } = useWorkspaceScope()
  const allStages = useStages()

  useEffect(() => {
    fetchSettings().then(s => {
      setConfigured(s.configured)
      if (!s.configured) setShowWizard(true)
    }).catch(() => setConfigured(false))
  }, [])

  const load = useCallback(async () => {
    try {
      const [a, t, w] = await Promise.all([
        fetchAgents(), fetchTasks({ limit: 300 }), fetchWorkspaces(),
      ])
      setAgents(a.agents)
      setTasks(t.tasks)
      setWorkspaces(w.workspaces)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection failed')
    }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 3000)
    return () => clearInterval(interval)
  }, [load])

  // Cluster keys to render: narrowed to one workspace if scoped, else
  // every known workspace plus an "Unassigned" bucket if there's any
  // activity with no project.
  const clusterKeys = useMemo(() => {
    if (scope) return [scope]
    const keys = workspaces.map(w => w.id)
    const hasUnassigned = agents.some(a => !a.project_id) || tasks.some(t => !t.project)
    return hasUnassigned ? [...keys, UNASSIGNED] : keys
  }, [scope, workspaces, agents, tasks])

  if (configured === null) return null

  return (
    <DeskLayout width={850}>
      {showWizard && (
        <SetupWizard
          onComplete={() => { setConfigured(true); setShowWizard(false) }}
          onSkip={() => setShowWizard(false)}
        />
      )}

      {!showWizard && (
        <>
          {error && (
            <Card style={{ marginBottom: 16, border: '1px solid var(--err)' }}>
              <span style={{ color: 'var(--err)', fontSize: 13 }}>{error} — retrying…</span>
            </Card>
          )}

          {workspaces.length === 0 && (
            <Card style={{ marginBottom: clusterKeys.length > 0 ? 16 : undefined }}>
              <div style={{ textAlign: 'center', padding: 20, color: 'var(--mut)' }}>
                No workspaces yet.{' '}
                <button onClick={() => setShowNewWorkspace(true)} style={{ color: 'var(--acc)', fontWeight: 600 }}>+ Create workspace</button>
                {' '}to point a session at a real project, or{' '}
                <button onClick={() => setShowNewSession(true)} style={{ color: 'var(--acc)', fontWeight: 600 }}>+ New session</button> without one.
              </div>
            </Card>
          )}

          {clusterKeys.map(key => (
            <WorkspaceCluster
              key={key}
              workspace={key === UNASSIGNED ? null : workspaces.find(w => w.id === key) || null}
              agents={agents.filter(a => (a.project_id || UNASSIGNED) === key)}
              tasks={tasks.filter(t => (t.project || UNASSIGNED) === key)}
              onChanged={load}
              onNewSession={() => setShowNewSession(true)}
              allStages={allStages}
            />
          ))}
        </>
      )}

      <NewSessionDialog open={showNewSession} onClose={() => setShowNewSession(false)} defaultWorkspace={scope} />
      {showNewWorkspace && (
        <WorkspaceDialog
          workspace={null}
          onClose={() => setShowNewWorkspace(false)}
          onSaved={() => { setShowNewWorkspace(false); load() }}
        />
      )}
    </DeskLayout>
  )
}

function WorkspaceCluster({ workspace, agents, tasks, onChanged, onNewSession, allStages }: {
  workspace: Workspace | null
  agents: AgentInfo[]
  tasks: TaskSummary[]
  onChanged: () => void
  onNewSession: () => void
  allStages: Stage[]
}) {
  const navigate = useNavigate()
  const openTasks = tasks.filter(t => stageForStatus(allStages, t.status)?.key === 'open')
  const blockedTask = tasks.find(t => t.status === 'blocked')
  const upNext = tasks.filter(t => (t.status === 'open' || t.status === 'planned') && !t.assigned_to).slice(0, 5)

  const handleStart = async (taskId?: string) => {
    const session = await createSession({ prompt: '', mode: 'agent', project_id: workspace?.id, task_id: taskId })
    navigate(`/agent/${session.id}`)
  }

  return (
    <div style={{ border: '2px dashed var(--line2)', borderRadius: 20, padding: 20, marginBottom: 24 }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 12px', borderRadius: 20, background: 'var(--card)', boxShadow: 'var(--shadow)' }}>
          <span style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--ink)' }}>{workspace?.name || 'Unassigned'}</span>
          {workspace?.repository && <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>{workspace.repository}</span>}
          {workspace?.runtime && <Chip mono>{workspace.runtime}</Chip>}
        </div>
        <span style={{ fontSize: 12, color: 'var(--mut)', whiteSpace: 'nowrap' }}>
          {agents.length} agent{agents.length !== 1 ? 's' : ''} · {openTasks.length} open task{openTasks.length !== 1 ? 's' : ''}
        </span>
      </div>

      {blockedTask && <BlockerHero task={blockedTask} onChanged={onChanged} />}

      {/* All active sessions, not just currently-mid-turn ones — an
          idle-between-turns or assistant-mode-waiting-for-input session
          still needs to be visible and clickable, not just ones with
          running===true at this exact instant. RunningAgentCard's body
          strip already distinguishes "working…" vs "idle". */}
      {agents.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          {agents.map(agent => (
            <RunningAgentCard key={agent.id} agent={agent} task={tasks.find(t => t.id === agent.task_id)} onDeleted={onChanged} />
          ))}
        </div>
      )}

      {/* Footer row: up next + pipeline counts */}
      <div style={{ display: 'flex', gap: 16 }}>
        <div style={{ flex: 1, border: '1px dashed var(--line2)', borderRadius: 14, padding: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--mut)' }}>
              Up next {workspace && `· auto-assign · max ${workspace.max_concurrent}`}
            </span>
            {workspace && (
              <Toggle
                small
                checked={workspace.auto_assign}
                onChange={checked => updateWorkspace(workspace.id, { auto_assign: checked }).then(onChanged)}
              />
            )}
          </div>
          {upNext.length === 0 && <div style={{ fontSize: 12, color: 'var(--mut2)' }}>Nothing queued</div>}
          {upNext.map(t => (
            <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: priorityColor(t.priority), flexShrink: 0 }} />
              <span onClick={() => navigate(`/tasks/${t.id}`)} style={{ flex: 1, fontSize: 12.5, color: 'var(--ink2)', cursor: 'pointer' }}>{t.title}</span>
              <button onClick={() => handleStart(t.id)} style={{ fontSize: 10.5, fontWeight: 700, padding: '2px 8px', borderRadius: 6, background: 'var(--ok-soft)', color: 'var(--ok)' }}>▶ Start</button>
            </div>
          ))}
        </div>
        <div style={{ width: 220, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Card style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>
            {enabledStages(allStages).map(s => (
              <div key={s.key} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                <span>{s.label}</span>
                <span style={{ color: 'var(--ink2)' }}>{tasks.filter(t => stageForStatus(allStages, t.status)?.key === s.key).length}</span>
              </div>
            ))}
          </Card>
          <button onClick={() => navigate('/review')} style={{ fontSize: 11.5, color: 'var(--acc)', fontWeight: 600, textAlign: 'left' }}>Review →</button>
          <button onClick={onNewSession} style={{ fontSize: 11.5, color: 'var(--mut)', textAlign: 'left' }}>+ New session</button>
        </div>
      </div>
    </div>
  )
}

function BlockerHero({ task, onChanged }: { task: TaskSummary; onChanged: () => void }) {
  const navigate = useNavigate()
  const [reply, setReply] = useState('')
  const [detail, setDetail] = useState<{ question: string; options: string[] } | null>(null)
  const [sending, setSending] = useState(false)

  useEffect(() => {
    // The list endpoint doesn't include the progress log — fetch the
    // task's own blocker question/options from its detail on demand.
    let cancelled = false
    fetchTask(task.id).then(t => {
      if (cancelled) return
      const last = [...t.progress].reverse().find(p => p.blocker?.question)
      if (last?.blocker) setDetail({ question: last.blocker.question, options: last.blocker.options })
    }).catch(() => {})
    return () => { cancelled = true }
  }, [task.id])

  const answer = async (text: string) => {
    if (!text.trim() || !task.assigned_to) return
    setSending(true)
    try {
      await sendMessage(task.assigned_to, text.trim())
      await updateTask(task.id, { status: 'in_progress' })
      onChanged()
    } finally {
      setSending(false)
    }
  }

  return (
    <Card style={{ border: '2px solid var(--warn)', boxShadow: 'var(--shadow-lg)', marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--warn)' }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{task.title}</span>
        <Chip color="var(--warn-ink)" soft>NEEDS YOU</Chip>
        <span onClick={() => navigate(`/tasks/${task.id}`)} style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--acc)', cursor: 'pointer' }}>{task.id}</span>
      </div>
      {detail?.question && <div style={{ fontSize: 12.5, fontStyle: 'italic', color: 'var(--ink2)', marginBottom: 10 }}>{detail.question}</div>}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {detail?.options.map(o => (
          <button key={o} disabled={sending} onClick={() => answer(o)} style={{ fontSize: 12, padding: '4px 10px', borderRadius: 8, background: 'var(--acc-soft)', color: 'var(--acc)', fontWeight: 600 }}>{o}</button>
        ))}
        <input
          value={reply}
          onChange={e => setReply(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { answer(reply); setReply('') } }}
          placeholder="Reply…"
          style={{ flex: 1, minWidth: 120, padding: '5px 10px', borderRadius: 8, border: '1px solid var(--line2)', background: 'var(--card2)', color: 'var(--ink)', fontSize: 12.5, outline: 'none' }}
        />
      </div>
    </Card>
  )
}

function RunningAgentCard({ agent, task, onDeleted }: { agent: AgentInfo; task?: TaskSummary; onDeleted: () => void }) {
  const navigate = useNavigate()
  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ok)' }} />
        <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--ink)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {task?.title || agent.id}
        </span>
        {task && <span style={{ fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>{task.progress_count}/{task.steps_count || task.criteria_count}</span>}
      </div>
      <div style={{ background: 'var(--card2)', borderRadius: 8, padding: '6px 8px', marginBottom: 8, fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>
        {agent.running ? 'working…' : 'idle'}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10.5, color: 'var(--mut)' }}>
        <span style={{ color: agent.mode === 'assistant' ? 'var(--warn-ink)' : 'var(--ok)', fontWeight: 700 }}>{agent.mode === 'assistant' ? 'driving' : 'watching'}</span>
        <span>{agent.tokens_used.toLocaleString()} tok</span>
        <button onClick={() => deleteAgent(agent.id).then(onDeleted)} style={{ color: 'var(--mut)' }}>✕</button>
        <button onClick={() => navigate(`/agent/${agent.id}`)} style={{ marginLeft: 'auto', color: 'var(--acc)', fontWeight: 600 }}>Open →</button>
      </div>
    </Card>
  )
}

export default Dashboard
