import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchTasks, type TaskSummary } from '../../lib/api'
import { useWorkspaceScope } from '../../lib/workspaceContext'
import { useStages, enabledStages, stageForStatus } from '../../lib/stages'
import { statusStyle } from '../../lib/statusColors'
import { priorityColor } from '../../lib/priorityColors'
import { Card, Chip } from '../../components/primitives'

const PRIORITY_ORDER: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 }

/** List tab of the Tasks screen — stage filter chips + task rows, per
 * design_handoff_atelier_cockpit/README.md §3. */
function List({ reloadSignal }: { reloadSignal?: number } = {}) {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [stageFilter, setStageFilter] = useState<string | null>(null)
  const { workspace } = useWorkspaceScope()
  const navigate = useNavigate()

  const load = useCallback(async () => {
    try {
      const data = await fetchTasks({ limit: 200, project: workspace || undefined })
      setTasks(data.tasks.sort((a, b) => (PRIORITY_ORDER[a.priority] ?? 2) - (PRIORITY_ORDER[b.priority] ?? 2)))
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

  const allStages = useStages()
  const stages = enabledStages(allStages)
  const filtered = stageFilter
    ? tasks.filter(t => stageForStatus(allStages, t.status)?.key === stageFilter)
    : tasks

  return (
    <Card style={{ padding: 0, overflow: 'hidden' }}>
      <div style={{ display: 'flex', gap: 6, padding: 12, borderBottom: '1px solid var(--line)', flexWrap: 'wrap' }}>
        <Chip soft={stageFilter === null} color="var(--acc)" onClick={() => setStageFilter(null)}>All</Chip>
        {stages.map(s => (
          <Chip key={s.key} soft={stageFilter === s.key} color="var(--acc)" onClick={() => setStageFilter(s.key)}>{s.label}</Chip>
        ))}
      </div>

      {filtered.length === 0 && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--mut)', fontSize: 13 }}>
          No tasks yet. Create one to get started.
        </div>
      )}

      {filtered.map(t => {
        const s = statusStyle(t.status)
        const meta = t.steps_count || t.criteria_count
        return (
          <div
            key={t.id}
            onClick={() => navigate(`/tasks/${t.id}`)}
            style={{
              display: 'grid', gridTemplateColumns: '1fr 100px 110px 80px 90px',
              gap: 10, padding: '10px 14px', borderBottom: '1px solid var(--line)',
              alignItems: 'center', cursor: 'pointer', fontSize: 12.5,
            }}
          >
            <div>
              <div style={{ fontWeight: 500, color: 'var(--ink)', marginBottom: 2 }}>{t.title}</div>
              <div style={{ fontSize: 10.5, color: 'var(--mut)', fontFamily: 'var(--font-mono)' }}>{t.id}</div>
            </div>
            <div style={{ color: 'var(--mut)', fontSize: 11.5 }}>{t.project || '—'}</div>
            <div style={{ color: s.color, fontWeight: 600, fontSize: 11.5, display: 'flex', alignItems: 'center', gap: 4 }}>{s.glyph} {s.label}</div>
            <div style={{ color: priorityColor(t.priority), fontWeight: 700, fontSize: 10.5, textTransform: 'uppercase' }}>{t.priority}</div>
            <div style={{ fontSize: 11, color: 'var(--mut)', fontFamily: 'var(--font-mono)' }}>{t.progress_count}/{meta || '—'}</div>
          </div>
        )
      })}
    </Card>
  )
}

export default List
