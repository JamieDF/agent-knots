import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createSession, type TaskSummary } from '../../lib/api'
import { enabledStages, stageForStatus } from '../../lib/stages'
import { statusStyle } from '../../lib/statusColors'
import { priorityColor } from '../../lib/priorityColors'
import { computeAgentState, AGENT_STATE_TOKENS } from '../../lib/agentState'
import { useTaskList } from '../../lib/useTaskList'
import { Card, Chip, Spinner } from '../../components/primitives'

/** List tab of the Tasks screen — a dense, table-like grid of task rows
 * sharing the board card's visual language: priority left-border, project
 * chip, status dot, live agent indicator, step pips, and a hover-revealed
 * ▶/🤖 split-button to start. */
function List({ reloadSignal }: { reloadSignal?: number } = {}) {
  const [stageFilter, setStageFilter] = useState<string | null>(null)
  const navigate = useNavigate()
  const { tasks, load, loading, workspace, allStages } = useTaskList(reloadSignal)
  const stages = enabledStages(allStages)
  const filtered = stageFilter
    ? tasks.filter(t => stageForStatus(allStages, t.status)?.key === stageFilter)
    : tasks

  const handleStart = async (task: TaskSummary, headless: boolean) => {
    const session = await createSession({ prompt: '', mode: 'agent', task_id: task.id, project_id: workspace || undefined })
    if (headless) load()
    else navigate(`/agent/${session.id}`)
  }

  return (
    <Card style={{ padding: 0, overflow: 'hidden' }}>
      {/* Filter chips — kept from the original, now with counts. */}
      <div style={{ display: 'flex', gap: 6, padding: 12, borderBottom: '1px solid var(--line)', flexWrap: 'wrap' }}>
        <Chip soft={stageFilter === null} color="var(--acc)" onClick={() => setStageFilter(null)}>
          All {tasks.length > 0 && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, opacity: 0.7 }}>{tasks.length}</span>}
        </Chip>
        {stages.map(s => {
          const count = tasks.filter(t => stageForStatus(allStages, t.status)?.key === s.key).length
          return (
            <Chip key={s.key} soft={stageFilter === s.key} color="var(--acc)" onClick={() => setStageFilter(s.key)}>
              {s.label} {count > 0 && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, opacity: 0.7 }}>{count}</span>}
            </Chip>
          )
        })}
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
          <Spinner />
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--mut)', fontSize: 13 }}>
          No tasks yet. Create one to get started.
        </div>
      ) : (
        <>
          {/* Column header */}
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 140px 110px 70px',
            gap: 10, padding: '6px 16px', borderBottom: '1px solid var(--line)',
            fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--mut2)',
          }}>
            <div>Task</div>
            <div>Agent</div>
            <div>Status</div>
            <div>Steps</div>
          </div>

          {filtered.map(t => {
            const s = statusStyle(t.status)
            const agentState = computeAgentState(!!t.agent_name, t.agent_running, t.agent_error)
            const st = agentState ? AGENT_STATE_TOKENS[agentState] : null
            const canStart = !t.assigned_to && !t.blocked_by_deps
            // Short id hint — last 4 hex chars of the id, not the full thing.
            const shortId = t.id.slice(-4)

            return (
              <div
                key={t.id}
                className="ak-list-row"
                onClick={() => navigate(`/tasks/${t.id}`)}
                title="Open task"
                style={{
                  display: 'grid', gridTemplateColumns: '1fr 140px 110px 70px',
                  gap: 10, padding: '8px 16px', borderBottom: '1px solid var(--line)',
                  alignItems: 'center', cursor: 'pointer', fontSize: 12.5,
                  borderLeft: `3px solid ${priorityColor(t.priority)}`,
                }}
              >
                {/* Title + project chip + short id */}
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, color: 'var(--ink)', fontSize: 12.5, marginBottom: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: st ? 0 : 28 }}>
                    {t.title}
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    {t.project && (
                      <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--ink2)', background: 'var(--card2)', padding: '1.5px 6px', borderRadius: 6 }}>{t.project}</span>
                    )}
                    <span style={{ fontSize: 10, color: 'var(--mut2)', fontFamily: 'var(--font-mono)' }}>…{shortId}</span>
                    {t.blocked_by_deps && <span title="Waiting on an unfinished dependency" style={{ fontSize: 10 }}>🔗</span>}
                  </div>
                </div>

                {/* Agent indicator — green/amber pill when live, — when not */}
                <div>
                  {st ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10.5, padding: '2px 7px', borderRadius: 6, background: st.soft }}>
                      <span
                        className={agentState === 'running' ? 'ak-pulse' : undefined}
                        style={{ width: 6, height: 6, borderRadius: '50%', background: st.color, color: st.color, flexShrink: 0, position: 'relative' }}
                      />
                      <span style={{ fontWeight: 600, color: st.color, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 90 }}>{t.agent_name}</span>
                    </span>
                  ) : (
                    <span style={{ fontSize: 10.5, color: 'var(--mut2)' }}>—</span>
                  )}
                </div>

                {/* Status dot + label */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, color: s.color, fontWeight: 600, fontSize: 11 }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: s.color, flexShrink: 0 }} />
                  {s.label}
                </div>

                {/* Step pips */}
                <div>
                  {t.steps_count > 0 ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                      {Array.from({ length: Math.min(t.steps_count, 5) }, (_, i) => (
                        <span key={i} style={{ width: 5, height: 5, borderRadius: '50%', background: i < t.steps_done ? 'var(--ok)' : 'var(--line2)' }} />
                      ))}
                      <span style={{ fontSize: 10, color: 'var(--mut)', fontFamily: 'var(--font-mono)', marginLeft: 2 }}>{t.steps_done}/{t.steps_count}</span>
                    </span>
                  ) : (
                    <span style={{ fontSize: 10, color: 'var(--mut2)', fontFamily: 'var(--font-mono)' }}>{t.progress_count}</span>
                  )}
                </div>

                {/* Hover split-button — same ▶/🤖 as the board, but
                    positioned at the end of the title cell. */}
                {!st && canStart && (
                  <div className="ak-list-action" style={{ gridColumn: '1', position: 'absolute', right: 16, display: 'flex', gap: 0 }}>
                    <button
                      onClick={e => { e.stopPropagation(); handleStart(t, false) }}
                      title="Start and open the thread"
                      style={{
                        width: 24, height: 22, padding: 0, border: 'none',
                        background: 'var(--acc)', color: 'var(--acc-ink)',
                        fontSize: 10, fontWeight: 700, cursor: 'pointer',
                        borderRadius: '5px 0 0 5px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                    >▶</button>
                    <button
                      onClick={e => { e.stopPropagation(); handleStart(t, true) }}
                      title="Start in the background (headless)"
                      style={{
                        width: 26, height: 22, padding: 0, border: '1px solid var(--line2)', borderLeft: 'none',
                        background: 'var(--card)', color: 'var(--ink2)',
                        fontSize: 11, fontWeight: 700, cursor: 'pointer',
                        borderRadius: '0 5px 5px 0', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                    >🤖</button>
                  </div>
                )}
              </div>
            )
          })}
        </>
      )}
    </Card>
  )
}

export default List
