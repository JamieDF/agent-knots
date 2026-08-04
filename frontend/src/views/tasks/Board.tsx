import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { updateTask, createSession, type TaskSummary } from '../../lib/api'
import { enabledStages, stageForStatus } from '../../lib/stages'
import { priorityColor } from '../../lib/priorityColors'
import { computeAgentState, AGENT_STATE_TOKENS } from '../../lib/agentState'
import { useTaskList } from '../../lib/useTaskList'
import TaskDialog from '../../components/TaskDialog'
import { Spinner } from '../../components/primitives'

/** Board tab of the Tasks screen — stage-driven columns backed by the
 * real Workflows stage config. */
function Board({ reloadSignal }: { reloadSignal?: number } = {}) {
  const [dialogStatus, setDialogStatus] = useState<string | null>(null)
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dragOverStage, setDragOverStage] = useState<string | null>(null)
  const [moveError, setMoveError] = useState<string | null>(null)
  const navigate = useNavigate()
  const { tasks, setTasks, load, loading, workspace, allStages } = useTaskList(reloadSignal)

  const handleMove = async (taskId: string, newStatus: string) => {
    try {
      await updateTask(taskId, { status: newStatus })
      setTasks(prev => prev.map(t => t.id === taskId ? { ...t, status: newStatus } : t))
      setMoveError(null)
    } catch (e) {
      setMoveError(e instanceof Error ? e.message : 'Failed to move task')
    }
  }

  const handleStart = async (task: TaskSummary, headless: boolean) => {
    const session = await createSession({ prompt: '', mode: 'agent', task_id: task.id, project_id: workspace || undefined })
    if (headless) load()
    else navigate(`/agent/${session.id}`)
  }

  const stages = enabledStages(allStages)
  const tasksForStage = (stageKey: string) =>
    tasks.filter(t => stageForStatus(allStages, t.status)?.key === stageKey)

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 60, flex: 1 }}>
        <Spinner />
      </div>
    )
  }

  return (
	    <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 12, flex: 1, minHeight: 0 }}>
	      {stages.map(stage => {
	        const items = tasksForStage(stage.key)
	        return (
	          <div
	            key={stage.key}
	            onDragOver={e => { e.preventDefault(); setDragOverStage(stage.key) }}
	            onDragLeave={e => {
	              const el = e.currentTarget as HTMLElement
	              if (!el.contains(e.relatedTarget as Node)) {
	                setDragOverStage(prev => prev === stage.key ? null : prev)
	              }
	            }}
	            onDrop={e => {
	              e.preventDefault()
	              const taskId = e.dataTransfer.getData('text/plain')
	              setDragOverStage(null)
	              setDraggingId(null)
	              if (taskId) handleMove(taskId, stage.statuses[0])
	            }}
	            style={{
	              flex: '1 1 0', minWidth: 230, maxWidth: 250, display: 'flex', flexDirection: 'column',
	              borderRadius: 12, transition: 'background 0.1s',
	              background: dragOverStage === stage.key ? 'var(--acc-soft)' : undefined,
	            }}
	          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', marginBottom: 8, borderRadius: 10, background: 'var(--card2)' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--mut)', flexShrink: 0 }} />
              <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--ink)' }}>{stage.label}</span>
              <span style={{ fontSize: 11, color: 'var(--mut)', fontFamily: 'var(--font-mono)' }}>{items.length}</span>
              <button
                onClick={() => setDialogStatus(stage.statuses[0])}
                title="Add task"
                style={{ marginLeft: 'auto', width: 20, height: 20, borderRadius: 6, color: 'var(--mut)', fontSize: 13, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
              >+</button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 4, flex: 1, minHeight: 40 }}>
              {items.map(task => (
                <TaskCard
                  key={task.id}
                  task={task}
                  dragging={draggingId === task.id}
                  onDragStart={() => setDraggingId(task.id)}
                  onDragEnd={() => { setDraggingId(null); setDragOverStage(null) }}
                  onOpen={() => navigate(`/tasks/${task.id}`)}
                  onStart={(headless: boolean) => handleStart(task, headless)}
                  onOpenAgent={() => navigate(`/agent/${task.assigned_to}`)}
                />
              ))}
              {items.length === 0 && (
                <div style={{ padding: 16, fontSize: 12, color: 'var(--mut2)', textAlign: 'center' }}>No tasks</div>
              )}
            </div>
          </div>
        )
      })}

      {dialogStatus !== null && (
        <TaskDialog
          open
          initialStatus={dialogStatus}
          onClose={() => setDialogStatus(null)}
          onSaved={() => { setDialogStatus(null); load() }}
        />
      )}

      {moveError && (
        <div style={{
          position: 'fixed', bottom: 16, left: '50%', transform: 'translateX(-50%)', zIndex: 200,
          padding: '8px 16px', borderRadius: 10, background: 'var(--err)', color: '#fff',
          fontSize: 13, fontWeight: 600, boxShadow: 'var(--shadow-lg)', cursor: 'pointer',
        }} onClick={() => setMoveError(null)}>
          {moveError}
        </div>
      )}
    </div>
  )
}

/** A board card. The whole card is a click target for Task Detail; a
 * hover-revealed ▶ starts an agent (or jumps to the thread if one's
 * already running). Priority is the left-border color only — no text.
 * Drag-and-drop handles stage moves, so there are no stage buttons.
 *
 * The agent strip reuses the same green/amber/red dot as TaskDetail so
 * the live state reads the same everywhere. */
function TaskCard({ task, dragging, onDragStart, onDragEnd, onOpen, onStart, onOpenAgent }: {
  task: TaskSummary
  dragging: boolean
  onDragStart: () => void
  onDragEnd: () => void
  onOpen: () => void
  onStart: (headless: boolean) => void
  onOpenAgent: () => void
}) {
  // agent_name is populated only when the writer is in session_manager
  // .active — task.assigned_to is never cleared on stop, so it can name
  // a session that died long ago. Key the strip off the live join, not
  // the stale id.
  const agentState = computeAgentState(!!task.agent_name, task.agent_running, task.agent_error)
  const st = agentState ? AGENT_STATE_TOKENS[agentState] : null
  const canStart = !task.assigned_to && !task.blocked_by_deps

  return (
    <div
      className="ak-card"
      draggable
      onDragStart={e => { e.dataTransfer.setData('text/plain', task.id); e.dataTransfer.effectAllowed = 'move'; onDragStart() }}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      title="Open task"
      style={{
        position: 'relative',
        background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 10,
        borderLeft: `3px solid ${priorityColor(task.priority)}`,
        padding: '11px 12px', cursor: 'pointer', boxShadow: 'var(--shadow)',
        opacity: dragging ? 0.4 : 1,
        transition: 'box-shadow 0.12s ease, transform 0.12s ease',
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginBottom: 7, lineHeight: 1.35, paddingRight: 22 }}>{task.title}</div>

      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {task.project && (
          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--ink2)', background: 'var(--card2)', padding: '1.5px 6px', borderRadius: 6 }}>{task.project}</span>
        )}
        {/* Status badges — only the ones the column doesn't already imply. */}
        {task.status === 'blocked' && (
          <span style={{ fontSize: 9.5, fontWeight: 700, padding: '1px 6px', borderRadius: 6, background: 'var(--warn-soft)', color: 'var(--warn-ink)' }}>⚠ BLOCKED</span>
        )}
        {task.blocked_by_deps && (
          <span title="Waiting on an unfinished dependency" style={{ fontSize: 9.5, fontWeight: 700, padding: '1px 6px', borderRadius: 6, background: 'var(--warn-soft)', color: 'var(--warn-ink)' }}>🔗 DEP</span>
        )}
        {task.status === 'planned' && (
          <span style={{ fontSize: 9.5, fontWeight: 700, padding: '1px 6px', borderRadius: 6, background: 'var(--acc-soft)', color: 'var(--acc)' }}>PLANNED</span>
        )}
        {/* Step progress pips — only if the task has steps. */}
        {task.steps_count > 0 && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
            {Array.from({ length: task.steps_count }, (_, i) => (
              <span key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: i < task.steps_done ? 'var(--ok)' : 'var(--line2)' }} />
            ))}
            <span style={{ fontSize: 10, color: 'var(--mut)', fontFamily: 'var(--font-mono)', marginLeft: 2 }}>{task.steps_done}/{task.steps_count}</span>
          </span>
        )}
      </div>

      {/* Live agent strip — same green/amber/red dot as TaskDetail.
          Given its own inset tinted background so it reads as a distinct
          footer section even at rest, not just on hover. */}
      {st && (
        <div
          onClick={e => { e.stopPropagation(); onOpenAgent() }}
          title={`Open ${task.agent_name}'s thread · ${st.label}`}
          style={{
            display: 'flex', alignItems: 'center', gap: 7,
            marginTop: 9, marginLeft: -12, marginRight: -12, marginBottom: -11,
            padding: '7px 12px',
            background: st.soft,
            borderBottomLeftRadius: 10, borderBottomRightRadius: 10,
            borderTop: '1px solid var(--line)',
          }}
        >
          <span
            className={agentState === 'running' ? 'ak-pulse' : undefined}
            style={{ width: 7, height: 7, borderRadius: '50%', background: st.color, color: st.color, flexShrink: 0, position: 'relative' }}
          />
          <span style={{ fontSize: 11, fontWeight: 600, color: st.color }}>{task.agent_name}</span>
          <span style={{ fontSize: 11, color: 'var(--mut)' }}>· {st.label}</span>
        </div>
      )}

      {/* Hover-revealed action. When an agent is live, it's a single
          button jumping to the thread. When idle, it's a split button:
          a ▶ that on hover fans out into Start (watch) + Start headless.
          See .ak-card-action / .ak-split in index.css for the reveal. */}
      {st ? (
        <button
          className="ak-card-action"
          onClick={e => { e.stopPropagation(); onOpenAgent() }}
          title="Open thread"
          style={{
            position: 'absolute', right: 8, top: 9,
            width: 24, height: 24, borderRadius: 6, padding: 0,
            background: st.color, color: 'var(--acc-ink)',
            fontSize: 10, fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer', boxShadow: 'var(--shadow)', border: 'none',
          }}
        >→</button>
      ) : (
        <div className="ak-card-action ak-split" style={{ position: 'absolute', right: 8, top: 9, display: 'flex', gap: 0 }}>
          <button
            onClick={e => { e.stopPropagation(); onStart(false) }}
            title="Start and open the thread"
            disabled={!canStart}
            style={{
              width: 24, height: 24, padding: 0, border: 'none',
              background: 'var(--acc)', color: 'var(--acc-ink)',
              fontSize: 10, fontWeight: 700, cursor: canStart ? 'pointer' : 'not-allowed',
              borderRadius: '6px 0 0 6px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: 'var(--shadow)',
            }}
          >▶</button>
          {/* Headless half — hidden until the card is hovered (see
              .ak-split-headless in index.css). Uses opacity + transform
              rather than width:0 so the button stays a real layout
              element the browser can hover/click even mid-transition.
              🤖 = the agent going off to work on its own (autonomous). */}
          <button
            className="ak-split-headless"
            onClick={e => { e.stopPropagation(); onStart(true) }}
            title="Start in the background (headless)"
            disabled={!canStart}
            style={{
              height: 24, padding: 0,
              border: 'none', background: 'var(--card2)', color: 'var(--ink2)',
              fontSize: 11, fontWeight: 700, cursor: canStart ? 'pointer' : 'not-allowed',
              borderRadius: '0 6px 6px 0',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              whiteSpace: 'nowrap',
              boxShadow: 'var(--shadow)',
            }}
          >🤖</button>
        </div>
      )}
    </div>
  )
}

export default Board
