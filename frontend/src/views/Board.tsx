import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchTasks, updateTask, type TaskSummary } from '../lib/api'
import { getActiveWorkspace } from '../lib/workspace'
import CreateTaskDialog from '../components/CreateTaskDialog'

const COLUMNS = [
  { status: 'draft',       label: 'Draft',       color: 'var(--muted-2)' },
  { status: 'open',        label: 'Todo',         color: 'var(--fg-soft)' },
  { status: 'planned',     label: 'Planned',      color: 'var(--info)' },
  { status: 'in_progress', label: 'In Progress',  color: 'var(--running)' },
  { status: 'review',      label: 'Review',       color: 'oklch(70% 0.14 295)' },
  { status: 'done',        label: 'Done',         color: 'var(--done)' },
]

const PRIORITY_COLORS: Record<string, string> = {
  urgent: 'var(--blocked)', high: 'oklch(76% 0.16 65)', medium: 'var(--info)', low: 'var(--muted)',
}

export default function Board() {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState<string | null>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    try {
      const ws = getActiveWorkspace()
      const data = await fetchTasks({ limit: 100, project: ws || undefined })
      setTasks(data.tasks)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [load])

  const handleStatusChange = async (taskId: string, newStatus: string) => {
    await updateTask(taskId, { status: newStatus })
    setTasks(prev => prev.map(t => t.id === taskId ? { ...t, status: newStatus } : t))
  }


  const tasksByStatus = (status: string) =>
    tasks.filter(t => t.status === status).sort((a, b) => {
      const pa = { urgent: 0, high: 1, medium: 2, low: 3 }[a.priority] ?? 2
      const pb = { urgent: 0, high: 1, medium: 2, low: 3 }[b.priority] ?? 2
      return pa - pb
    })

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Board columns */}
      <div style={{ flex: 1, display: 'flex', gap: 0, overflowX: 'auto', overflowY: 'hidden' }}>
        {COLUMNS.map(col => {
          const items = tasksByStatus(col.status)
          return (
            <div key={col.status} style={{
              flex: 1, minWidth: 200, display: 'flex', flexDirection: 'column',
              borderRight: '1px solid var(--border-subtle)',
              background: col.status === 'done' ? 'oklch(12% 0.003 260)' : undefined,
            }}>
              {/* Column header */}
              <div style={{
                padding: '10px 12px', borderBottom: '1px solid var(--border-subtle)',
                display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
              }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: col.color, flexShrink: 0 }} />
                <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--fg-soft)' }}>{col.label}</span>
                <span style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                  {items.length}
                </span>
                <button
                  onClick={() => setShowCreate(col.status)}
                  style={{
                    marginLeft: 'auto', width: 22, height: 22, borderRadius: 4,
                    border: '1px solid var(--border)', background: 'transparent',
                    color: 'var(--muted)', fontSize: 14, cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                  title="Add task"
                >+</button>
              </div>

              {/* Task cards */}
              <div style={{ flex: 1, overflowY: 'auto', padding: 6 }}>
                {items.map(task => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    expanded={expandedId === task.id}
                    onExpand={() => setExpandedId(expandedId === task.id ? null : task.id)}
                    onStatusChange={(s) => handleStatusChange(task.id, s)}
                    onClick={() => navigate(`/tasks/${task.id}`)}
                  />
                ))}
                {items.length === 0 && (
                  <div style={{ padding: 16, fontSize: 12, color: 'var(--muted-2)', textAlign: 'center' }}>
                    No tasks
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
      {showCreate && <CreateTaskDialog onClose={() => setShowCreate(null)} onCreated={() => { setShowCreate(null); load() }} />}
    </div>
  )
}

function TaskCard({ task, expanded, onExpand, onStatusChange, onClick }: {
  task: TaskSummary; expanded: boolean; onExpand: () => void;
  onStatusChange: (s: string) => void; onClick: () => void;
}) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6,
      padding: '8px 10px', marginBottom: 6, cursor: 'pointer', fontSize: 12,
      transition: 'border-color 0.15s',
      borderLeft: `3px solid ${PRIORITY_COLORS[task.priority] || 'var(--muted)'}`,
    }} onClick={onExpand}>
      <div style={{ fontWeight: 500, color: 'var(--fg)', marginBottom: 4, lineHeight: 1.3 }}>
        {task.title}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
          {task.id.slice(0, 20)}
        </span>
        {task.tags.map(tag => (
          <span key={tag} style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'var(--surface-raised)', color: 'var(--fg-soft)' }}>
            {tag}
          </span>
        ))}
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border-subtle)' }} onClick={e => e.stopPropagation()}>
          <div style={{ fontSize: 11, color: 'var(--fg-soft)', marginBottom: 6 }}>
            Priority: <span style={{ textTransform: 'capitalize', color: PRIORITY_COLORS[task.priority] }}>{task.priority}</span>
            {task.assigned_to && <> · Assigned: <span style={{ fontFamily: 'var(--font-mono)' }}>{task.assigned_to}</span></>}
          </div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
            {COLUMNS.map(col => (
              <button key={col.status} onClick={() => onStatusChange(col.status)}
                style={{
                  fontSize: 10, padding: '2px 6px', borderRadius: 3, border: '1px solid var(--border)',
                  background: task.status === col.status ? col.color.replace(')', ' / 0.15)').replace('oklch', 'oklch') : 'transparent',
                  color: task.status === col.status ? col.color : 'var(--muted)',
                  cursor: 'pointer', fontFamily: 'inherit',
                }}>
                {col.label}
              </button>
            ))}
          </div>
          <button onClick={onClick} style={{ fontSize: 11, color: 'var(--info)', cursor: 'pointer', border: 0, background: 'none', padding: 0 }}>
            View full details →
          </button>
          <button onClick={async (e) => {
            e.stopPropagation()
            const { createSession } = await import('../lib/api')
            const session = await createSession({ prompt: '', mode: 'agent', task_id: task.id, project_id: getActiveWorkspace() || undefined })
            // We're in a callback, can't use hooks — just set location.
            window.location.hash = '#/agent/' + session.id
          }} style={{ fontSize: 11, color: 'var(--running)', cursor: 'pointer', border: '1px solid var(--running)', borderRadius: 4, background: 'transparent', padding: '2px 8px', marginLeft: 8, fontFamily: 'inherit' }}>
            ▶ Start session
          </button>
        </div>
      )}
    </div>
  )
}
