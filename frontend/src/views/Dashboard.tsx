import { useEffect, useMemo, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import SetupWizard from '../components/SetupWizard'
import NewSessionDialog from '../components/NewSessionDialog'
import WorkspaceDialog from '../components/WorkspaceDialog'
import DeskLayout from '../components/DeskLayout'
import { Card, Toggle } from '../components/primitives'
import { priorityColor } from '../lib/priorityColors'
import { computeAgentState, AGENT_STATE_TOKENS } from '../lib/agentState'
import { useStages, enabledStages, stageForStatus, type Stage } from '../lib/stages'
import { useWorkspaceScope } from '../lib/workspaceContext'
import {
  fetchAgents, fetchSettings, fetchTasks, fetchTask, fetchWorkspaces, deleteAgent, sendMessage,
  updateTask, createSession, updateWorkspace, answerAgent,
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
    <DeskLayout scale="narrow">
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

  // Agent stats for the header — running vs waiting, using the same
  // state logic as the board/list/review.
  const runningCount = agents.filter(a => !a.advisory && a.running).length
  const waitingCount = agents.filter(a => !a.advisory && !a.running).length
  const writerAgents = agents.filter(a => !a.advisory)

  const handleStart = async (taskId: string | undefined, headless: boolean) => {
    const session = await createSession({ prompt: '', mode: 'agent', project_id: workspace?.id, task_id: taskId })
    if (headless) onChanged()
    else navigate(`/agent/${session.id}`)
  }

  const wsName = workspace?.name || 'Unassigned'
  const wsInitial = wsName.charAt(0).toUpperCase()

  return (
    <div className="ak-ws-box" style={{
      background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 16,
      boxShadow: 'var(--shadow)', marginBottom: 24, overflow: 'hidden',
    }}>
      {/* Header — icon avatar, name + repo, colored stat dots */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 20px', borderBottom: '1px solid var(--line)' }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'var(--acc-soft)', color: 'var(--acc)', fontSize: 16, fontWeight: 700,
        }}>{wsInitial}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--ink)', lineHeight: 1.2 }}>{wsName}</div>
          <div style={{ fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--mut)', lineHeight: 1.3 }}>
            {workspace?.repository ? `${workspace.repository}` : ''}
            {workspace?.repository && workspace?.runtime ? ' · ' : ''}
            {workspace?.runtime}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginLeft: 'auto' }}>
          {runningCount > 0 && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--ink2)' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--ok)' }} />
              <b style={{ color: 'var(--ink)', fontWeight: 700 }}>{runningCount}</b> running
            </span>
          )}
          {waitingCount > 0 && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--ink2)' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--warn-ink)' }} />
              <b style={{ color: 'var(--ink)', fontWeight: 700 }}>{waitingCount}</b> waiting
            </span>
          )}
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--ink2)' }}>
            <b style={{ color: 'var(--ink)', fontWeight: 700 }}>{openTasks.length}</b> open
          </span>
        </div>
      </div>

      {blockedTask && <BlockerHero task={blockedTask} onChanged={onChanged} />}

      {/* Agent cards */}
      {writerAgents.length > 0 && (
        <div style={{ padding: '16px 20px 8px' }}>
          <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--mut2)', marginBottom: 10 }}>Active agents</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
            {writerAgents.map(agent => (
              <RunningAgentCard key={agent.id} agent={agent} task={tasks.find(t => t.id === agent.task_id)} onDeleted={onChanged} />
            ))}
          </div>
        </div>
      )}

      {/* Empty state — only when no agents AND no blocker */}
      {writerAgents.length === 0 && !blockedTask && (
        <div style={{ padding: '36px 20px', textAlign: 'center' }}>
          <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.4 }}>💤</div>
          <div style={{ fontSize: 13, color: 'var(--mut)' }}>No active agents. Start one from the queue below or launch a new session.</div>
        </div>
      )}

      {/* Footer: queue + pipeline */}
      <div style={{ display: 'flex', borderTop: '1px solid var(--line)' }}>
        {/* Queue */}
        <div style={{ flex: 1, padding: '14px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ flex: 1, fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--mut2)' }}>
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
          {upNext.length === 0 && <div style={{ fontSize: 12, color: 'var(--mut2)', padding: '4px 0' }}>Nothing queued</div>}
          {upNext.map(t => (
            <div key={t.id} className="ak-queue-item" style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', margin: '0 -8px',
              borderRadius: 8, cursor: 'default', transition: 'background 0.1s',
            }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: priorityColor(t.priority), flexShrink: 0 }} />
              <span onClick={() => navigate(`/tasks/${t.id}`)} style={{ flex: 1, fontSize: 12, color: 'var(--ink2)', cursor: 'pointer', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.title}</span>
              {/* Hover-revealed split: ▶ watch + 🤖 headless, same as board */}
              <div className="ak-queue-split" style={{ display: 'flex', gap: 0, opacity: 0, transition: 'opacity 0.12s' }}>
                <button onClick={() => handleStart(t.id, false)} title="Start and open the thread" style={{ width: 22, height: 22, padding: 0, border: 'none', background: 'var(--acc)', color: 'var(--acc-ink)', fontSize: 9, fontWeight: 700, cursor: 'pointer', borderRadius: '5px 0 0 5px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>▶</button>
                <button onClick={() => handleStart(t.id, true)} title="Start in the background (headless)" style={{ width: 24, height: 22, padding: 0, border: '1px solid var(--line2)', borderLeft: 'none', background: 'var(--card)', color: 'var(--ink2)', fontSize: 10, fontWeight: 700, cursor: 'pointer', borderRadius: '0 5px 5px 0', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>🤖</button>
              </div>
            </div>
          ))}
        </div>

        {/* Pipeline */}
        <div style={{ width: 190, padding: '14px 20px', borderLeft: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: 5 }}>
          {enabledStages(allStages).map(s => {
            const count = tasks.filter(t => stageForStatus(allStages, t.status)?.key === s.key).length
            const isReview = s.key === 'review' && count > 0
            return (
              <div
                key={s.key}
                onClick={isReview ? () => navigate('/review') : undefined}
                style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11,
                  cursor: isReview ? 'pointer' : 'default',
                  borderRadius: isReview ? 6 : 0, padding: isReview ? '2px 6px' : '2px 0', margin: isReview ? '0 -6px' : 0,
                  background: isReview ? 'var(--warn-soft)' : undefined,
                }}
              >
                <span style={{ color: isReview ? 'var(--warn-ink)' : 'var(--mut)', fontWeight: isReview ? 600 : 400 }}>{s.label}</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: isReview ? 'var(--warn-ink)' : 'var(--ink2)', fontWeight: 600 }}>
                  {count}{isReview ? ' →' : ''}
                </span>
              </div>
            )
          })}
          <div style={{ height: 1, background: 'var(--line)', margin: '6px 0' }} />
          <button onClick={onNewSession} style={{
            fontSize: 11.5, fontWeight: 600, padding: '6px 0', borderRadius: 7, border: 'none', cursor: 'pointer',
            fontFamily: 'inherit', background: 'var(--acc)', color: 'var(--acc-ink)', textAlign: 'center', width: '100%',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
          }}>+ New session</button>
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
    <div style={{ padding: '14px 20px 0' }}>
      <div style={{
        display: 'flex', alignItems: 'flex-start', gap: 12, padding: '12px 16px',
        borderRadius: 10, background: 'var(--warn-soft)',
        border: '1px solid color-mix(in srgb, var(--warn) 30%, transparent)',
      }}>
        <div style={{
          width: 28, height: 28, borderRadius: 8, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'var(--warn)', color: '#fff', fontSize: 14, fontWeight: 700,
        }}>!</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{task.title}</span>
            <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: 'var(--warn)', color: '#fff' }}>NEEDS YOU</span>
          </div>
          {detail?.question && <div style={{ fontSize: 12, color: 'var(--ink2)', fontStyle: 'italic', marginBottom: 8, lineHeight: 1.4 }}>{detail.question}</div>}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            {detail?.options.map(o => (
              <button key={o} disabled={sending} onClick={() => answer(o)} style={{
                fontSize: 11, padding: '4px 11px', borderRadius: 6,
                border: '1px solid var(--line2)', background: 'var(--card)', color: 'var(--ink2)',
                fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', opacity: sending ? 0.6 : 1,
              }}>{o}</button>
            ))}
            <input
              value={reply}
              onChange={e => setReply(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { answer(reply); setReply('') } }}
              placeholder="Reply…"
              style={{ flex: 1, minWidth: 100, padding: '4px 10px', borderRadius: 6, border: '1px solid var(--line2)', background: 'var(--card)', color: 'var(--ink)', fontSize: 11.5, outline: 'none', fontFamily: 'inherit' }}
            />
            <button onClick={() => navigate(`/tasks/${task.id}`)} style={{ fontSize: 11, color: 'var(--mut)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', marginLeft: 'auto' }}>Open task →</button>
          </div>
        </div>
      </div>
    </div>
  )
}

function RunningAgentCard({ agent, task, onDeleted }: { agent: AgentInfo; task?: TaskSummary; onDeleted: () => void }) {
  const navigate = useNavigate()
  const [answer, setAnswer] = useState('')
  const [sending, setSending] = useState(false)
  const pq = agent.pending_question

  const agentState = computeAgentState(true, agent.running, agent.error) ?? 'idle'
  const st = AGENT_STATE_TOKENS[agentState]
  const stateLabel = agent.mode === 'assistant'
    ? (agent.running ? 'responding…' : 'paused')
    : st.label

  const handleAnswer = async (text: string) => {
    if (!text.trim() || sending) return
    setSending(true)
    try {
      await answerAgent(agent.id, text.trim())
      setAnswer('')
      onDeleted()
    } catch { setSending(false) }
  }

  return (
    <Card style={{ minWidth: 0, maxWidth: 420, overflow: 'hidden' }}>
      {/* Head — dot + title + name + step progress */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, minWidth: 0 }}>
        <span
          className={agentState === 'running' ? 'ak-pulse' : undefined}
          style={{ width: 8, height: 8, borderRadius: '50%', background: st.color, color: st.color, flexShrink: 0, position: 'relative' }}
        />
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {task?.title || agent.name}
        </span>
        {task && <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--mut)', flexShrink: 0 }}>{agent.name}</span>}
        {task && <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--mut)', flexShrink: 0 }}>{task.steps_done}/{task.steps_count || task.criteria_count}</span>}
      </div>

      {/* Pending question — card-level answer UI */}
      {pq ? (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 12, color: 'var(--ink)', fontStyle: 'italic', marginBottom: 6, lineHeight: 1.4 }}>
            ❓ {pq.question}
          </div>
          {pq.options && pq.options.length > 0 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
              {pq.options.map((o, i) => (
                <button key={i} disabled={sending} onClick={() => handleAnswer(o)}
                  style={{ fontSize: 11, padding: '3px 8px', borderRadius: 6, background: 'var(--acc-soft)', color: 'var(--acc)', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', border: 'none', opacity: sending ? 0.6 : 1 }}
                >{o}</button>
              ))}
            </div>
          )}
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={answer}
              onChange={e => setAnswer(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleAnswer(answer) }}
              placeholder="Answer…"
              disabled={sending}
              style={{ flex: 1, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--line2)', background: 'var(--card2)', color: 'var(--ink)', fontSize: 11.5, outline: 'none', fontFamily: 'inherit', opacity: sending ? 0.6 : 1 }}
            />
            <button onClick={() => handleAnswer(answer)} disabled={sending || !answer.trim()}
              style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', border: 'none', cursor: 'pointer', fontFamily: 'inherit', whiteSpace: 'nowrap', opacity: sending || !answer.trim() ? 0.6 : 1 }}
            >Answer</button>
          </div>
        </div>
      ) : (
        /* Activity strip — bordered, rounded, mono */
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          background: 'var(--card2)', border: '1px solid var(--line)', borderRadius: 8,
          padding: '6px 10px', marginBottom: 8,
          fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          <span style={{ color: st.color }}>●</span>
          {agent.last_activity || (agent.running ? 'working…' : 'idle')}
        </div>
      )}

      {/* Footer — state + tokens + cost + open */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 10.5, color: 'var(--mut)' }}>
        <span style={{ fontWeight: 700, fontSize: 11, color: st.color }}>{stateLabel}</span>
        <span>{agent.tokens_used.toLocaleString()} tok · ${agent.cost_usd.toFixed(3)}</span>
        <button onClick={() => deleteAgent(agent.id).then(onDeleted)} style={{ color: 'var(--mut)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, padding: 0 }}>✕</button>
        <button onClick={() => navigate(`/agent/${agent.id}`)} style={{ marginLeft: 'auto', color: 'var(--acc)', fontWeight: 600, background: 'none', border: 'none', cursor: 'pointer', fontSize: 10.5, fontFamily: 'inherit' }}>Open →</button>
      </div>
    </Card>
  )
}

export default Dashboard
