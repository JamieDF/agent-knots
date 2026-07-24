import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { enabledStages, stageForStatus } from '../../lib/stages'
import { statusStyle } from '../../lib/statusColors'
import { priorityColor } from '../../lib/priorityColors'
import { useTaskList } from '../../lib/useTaskList'
import { Card, Chip } from '../../components/primitives'

/** List tab of the Tasks screen — stage filter chips + task rows, per
 * design_handoff_atelier_cockpit/README.md §3. */
function List({ reloadSignal }: { reloadSignal?: number } = {}) {
  const [stageFilter, setStageFilter] = useState<string | null>(null)
  const navigate = useNavigate()
  const { tasks, allStages } = useTaskList(reloadSignal)
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
            <div style={{ color: s.color, fontWeight: 600, fontSize: 11.5, display: 'flex', alignItems: 'center', gap: 4 }}>
              {s.glyph} {s.label}
              {t.blocked_by_deps && <span title="Waiting on an unfinished dependency">🔗</span>}
            </div>
            <div style={{ color: priorityColor(t.priority), fontWeight: 700, fontSize: 10.5, textTransform: 'uppercase' }}>{t.priority}</div>
            <div style={{ fontSize: 11, color: 'var(--mut)', fontFamily: 'var(--font-mono)' }}>{t.progress_count}/{meta || '—'}</div>
          </div>
        )
      })}
    </Card>
  )
}

export default List
