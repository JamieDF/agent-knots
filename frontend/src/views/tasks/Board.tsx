import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchTasks, updateTask, createSession, type TaskSummary } from '../../lib/api'
import { useWorkspaceScope } from '../../lib/workspaceContext'
import { useStages, enabledStages, stageForStatus, type Stage } from '../../lib/stages'
import { priorityColor } from '../../lib/priorityColors'
import TaskDialog from '../../components/TaskDialog'

const PRIORITY_ORDER: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 }

/** Board tab of the Tasks screen — stage-driven columns per
 * design_handoff_atelier_cockpit/README.md §3, backed by the real
 * Workflows stage config (Phase 4). */
function Board({ reloadSignal }: { reloadSignal?: number } = {}) {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [dialogStatus, setDialogStatus] = useState<string | null>(null)
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dragOverStage, setDragOverStage] = useState<string | null>(null)
  const { workspace } = useWorkspaceScope()
  const navigate = useNavigate()
  const allStages = useStages()

  const load = useCallback(async () => {
    try {
      const data = await fetchTasks({ limit: 200, project: workspace || undefined })
      setTasks(data.tasks)
    } catch { /* ignore */ }
  }, [workspace])

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [load])

  // A task created elsewhere (the Tasks screen header's own dialog)
  // should show up immediately, not on the next poll tick.
  useEffect(() => { if (reloadSignal !== undefined) load() }, [reloadSignal]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleMove = async (taskId: string, newStatus: string) => {
    await updateTask(taskId, { status: newStatus })
    setTasks(prev => prev.map(t => t.id === taskId ? { ...t, status: newStatus } : t))
  }

  const handleStart = async (task: TaskSummary, headless: boolean) => {
    const session = await createSession({ prompt: '', mode: 'agent', task_id: task.id, project_id: workspace || undefined })
    if (headless) load() // refresh so the card picks up its new "AGENT" badge
    else navigate(`/agent/${session.id}`)
  }

  const stages = enabledStages(allStages)
  const tasksForStage = (stageKey: string) =>
    tasks
      .filter(t => stageForStatus(allStages, t.status)?.key === stageKey)
      .sort((a, b) => (PRIORITY_ORDER[a.priority] ?? 2) - (PRIORITY_ORDER[b.priority] ?? 2))

  return (
    <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 12 }}>
      {stages.map(stage => {
        const items = tasksForStage(stage.key)
        return (
          <div
            key={stage.key}
            onDragOver={e => { e.preventDefault(); setDragOverStage(stage.key) }}
            onDragLeave={() => setDragOverStage(prev => (prev === stage.key ? null : prev))}
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

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 4, minHeight: 40 }}>
              {items.map(task => (
                <TaskCard
                  key={task.id}
                  task={task}
                  expanded={expandedId === task.id}
                  dragging={draggingId === task.id}
                  onDragStart={() => setDraggingId(task.id)}
                  onDragEnd={() => { setDraggingId(null); setDragOverStage(null) }}
                  onExpand={() => setExpandedId(expandedId === task.id ? null : task.id)}
                  onMove={s => handleMove(task.id, s)}
                  onDetails={() => navigate(`/tasks/${task.id}`)}
                  onStart={headless => handleStart(task, headless)}
                  allStages={allStages}
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
    </div>
  )
}

function TaskCard({ task, expanded, dragging, onDragStart, onDragEnd, onExpand, onMove, onDetails, onStart, allStages }: {
  task: TaskSummary
  expanded: boolean
  dragging: boolean
  onDragStart: () => void
  onDragEnd: () => void
  onExpand: () => void
  onMove: (status: string) => void
  onDetails: () => void
  onStart: (headless: boolean) => void
  allStages: Stage[]
}) {
  const stages = enabledStages(allStages)
  return (
    <div
      onClick={onExpand}
      draggable
      onDragStart={e => { e.dataTransfer.setData('text/plain', task.id); e.dataTransfer.effectAllowed = 'move'; onDragStart() }}
      onDragEnd={onDragEnd}
      style={{
        background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 10,
        borderLeft: `3px solid ${priorityColor(task.priority)}`,
        padding: '10px 12px', cursor: 'grab', boxShadow: 'var(--shadow)',
        opacity: dragging ? 0.4 : 1,
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)', marginBottom: 6, lineHeight: 1.35 }}>{task.title}</div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--mut)' }}>{task.id}</span>
        {task.assigned_to && (
          <span style={{ fontSize: 9.5, fontWeight: 700, padding: '1px 6px', borderRadius: 6, background: 'var(--ok-soft)', color: 'var(--ok)' }}>AGENT</span>
        )}
        {task.status === 'blocked' && (
          <span style={{ fontSize: 9.5, fontWeight: 700, padding: '1px 6px', borderRadius: 6, background: 'var(--warn-soft)', color: 'var(--warn-ink)' }}>⚠ BLOCKED</span>
        )}
        {task.blocked_by_deps && (
          <span title="Waiting on an unfinished dependency" style={{ fontSize: 9.5, fontWeight: 700, padding: '1px 6px', borderRadius: 6, background: 'var(--warn-soft)', color: 'var(--warn-ink)' }}>🔗 DEP</span>
        )}
        {task.status === 'planned' && (
          <span style={{ fontSize: 9.5, fontWeight: 700, padding: '1px 6px', borderRadius: 6, background: 'var(--acc-soft)', color: 'var(--acc)' }}>PLANNED</span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 9.5, fontWeight: 700, textTransform: 'uppercase', color: priorityColor(task.priority) }}>{task.priority}</span>
      </div>

      {expanded && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line)' }} onClick={e => e.stopPropagation()}>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
            {stages.map(s => (
              <button
                key={s.key}
                onClick={() => onMove(s.statuses[0])}
                style={{
                  fontSize: 10, padding: '2px 7px', borderRadius: 6,
                  background: stageForStatus(allStages, task.status)?.key === s.key ? 'var(--acc-soft)' : 'var(--card2)',
                  color: stageForStatus(allStages, task.status)?.key === s.key ? 'var(--acc)' : 'var(--mut)',
                }}
              >
                {s.label}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button onClick={onDetails} style={{ fontSize: 11.5, color: 'var(--acc)', fontWeight: 600 }}>Details →</button>
            {!task.assigned_to && !task.blocked_by_deps && (
              <>
                <button onClick={() => onStart(false)} title="Start and open the thread now" style={{ fontSize: 11, padding: '2px 8px', borderRadius: 6, background: 'var(--ok-soft)', color: 'var(--ok)', fontWeight: 600 }}>
                  ▶ Start (watch)
                </button>
                <button onClick={() => onStart(true)} title="Start in the background — open the thread later from this card or Task Detail" style={{ fontSize: 11, padding: '2px 8px', borderRadius: 6, background: 'var(--card2)', color: 'var(--ink2)', fontWeight: 600 }}>
                  ⏵ Start headless
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default Board
