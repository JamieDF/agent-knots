import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import DeskLayout from '../components/DeskLayout'
import { Card, Chip, SectionLabel, Dialog, Field, inputStyle } from '../components/primitives'
import {
  fetchReviewTasks, fetchReviewDiffs, fetchReviewDiffText, approveReview, rejectReview, fetchTask,
  type ReviewTask, type ReviewDiff, type TaskDetail as TDetail,
} from '../lib/api'
import { priorityColor } from '../lib/priorityColors'
import { computeAgentState, AGENT_STATE_TOKENS } from '../lib/agentState'

type FileStatus = 'pending' | 'committed'

/** Review — tasks sitting in the review workflow stage. The list here
 * (not raw git diffs across every workspace, which is what this
 * screen used to be) is what actually needs a human's attention; click
 * into one to see its task details alongside its file changes. */
function Review() {
  const { id } = useParams<{ id: string }>()
  return id ? <ReviewTaskDetail key={id} taskId={id} /> : <ReviewTaskList />
}

function ReviewTaskList() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<ReviewTask[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  // Cached diffs per task — fetched on first expand, reused after.
  const [diffsByTask, setDiffsByTask] = useState<Record<string, ReviewDiff[]>>({})

  const load = useCallback(() => {
    fetchReviewTasks().then(r => setTasks(r.tasks)).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [load])

  const handleExpand = async (taskId: string) => {
    if (expandedId === taskId) { setExpandedId(null); return }
    setExpandedId(taskId)
    if (!diffsByTask[taskId]) {
      try {
        const res = await fetchReviewDiffs(taskId)
        setDiffsByTask(prev => ({ ...prev, [taskId]: res.diffs }))
      } catch { /* ignore — the accordion just shows nothing */ }
    }
  }

  return (
    <DeskLayout scale="narrow">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <div style={{ fontSize: 18, fontWeight: 700 }}>Review</div>
        <Chip color="var(--warn-ink)" soft>{tasks.length} waiting</Chip>
      </div>

      {tasks.length === 0 && (
        <Card><div style={{ textAlign: 'center', padding: 20, color: 'var(--mut)', fontSize: 13 }}>Nothing waiting on review.</div></Card>
      )}

      {tasks.map(t => {
        const agentState = computeAgentState(!!t.session_id, t.session_running, t.session_error)
        const st = agentState ? AGENT_STATE_TOKENS[agentState] : null
        const isOpen = expandedId === t.id
        const diffs = diffsByTask[t.id] || []

        return (
          <div
            key={t.id}
            className="ak-review-card"
            style={{
              background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 14,
              boxShadow: 'var(--shadow)', marginBottom: 10, overflow: 'hidden',
              borderLeft: `3px solid ${priorityColor(t.priority)}`,
              transition: 'box-shadow 0.12s ease',
            }}
          >
            {/* Clickable head — expands the accordion */}
            <div
              onClick={() => handleExpand(t.id)}
              style={{ cursor: 'pointer', padding: '14px 16px' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 12, color: 'var(--mut)', transition: 'transform 0.15s', transform: isOpen ? 'rotate(90deg)' : 'none' }}>▸</span>
                <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--ink)', flex: 1 }}>{t.title}</span>
                {t.project_name && <Chip mono>{t.project_name}</Chip>}
                {t.has_repo && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, fontFamily: 'var(--font-mono)' }}>
                    <span style={{ color: 'var(--ok)' }}>+{t.added}</span>
                    <span style={{ color: 'var(--err)' }}>−{t.deleted}</span>
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', gap: 14, alignItems: 'center', fontSize: 11.5, paddingLeft: 20 }}>
                {/* A non-git workspace has no file counts to report —
                    saying "0 files" would read as "nothing changed"
                    rather than "this isn't that kind of workspace". */}
                <span style={{ color: 'var(--ink2)' }}>
                  {t.has_repo ? `${t.file_count} file${t.file_count !== 1 ? 's' : ''}` : 'task review'}
                </span>
                <span style={{ color: 'var(--mut2)' }}>·</span>
                {st ? (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, padding: '2px 7px', borderRadius: 6, background: st.soft }}>
                    <span className={agentState === 'running' ? 'ak-pulse' : undefined} style={{ width: 6, height: 6, borderRadius: '50%', background: st.color, color: st.color, flexShrink: 0, position: 'relative' }} />
                    <span style={{ fontWeight: 600, color: st.color }}>{t.session_name}</span>
                    <span style={{ color: 'var(--mut)' }}>· {st.label}</span>
                  </span>
                ) : (
                  <span style={{ color: 'var(--mut)' }}>no active session</span>
                )}
                <span style={{ flex: 1 }} />
                {/* Review files → opens the full per-file approve/reject screen.
                    stopPropagation so it doesn't also toggle the accordion. */}
                <button
                  onClick={e => { e.stopPropagation(); navigate(`/review/${t.id}`) }}
                  title={t.has_repo ? 'Open full per-file review' : 'Open the review for this task'}
                  style={{ fontSize: 11.5, fontWeight: 600, padding: '4px 12px', borderRadius: 7, border: 'none', cursor: 'pointer', background: 'var(--acc)', color: 'var(--acc-ink)' }}
                >{t.has_repo ? 'Review files →' : 'Review task →'}</button>
              </div>
            </div>

            {/* Accordion body — inline diff preview, expanded on click */}
            {isOpen && (
              <div style={{ borderTop: '1px solid var(--line)', padding: '12px 16px' }}>
                {diffs.length === 0 && (
                  <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>
                    {t.has_repo
                      ? 'No pending changes.'
                      : "This workspace isn't a git repository — there are no file changes to show, so you're reviewing the task itself."}
                  </div>
                )}
                {diffs.map(d => (
                  <div key={d.file} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0', borderBottom: '1px solid var(--line)' }}>
                    <span style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink)' }}>{d.file}</span>
                    <span style={{ fontSize: 11, color: 'var(--ok)', fontFamily: 'var(--font-mono)' }}>+{d.added}</span>
                    <span style={{ fontSize: 11, color: 'var(--err)', fontFamily: 'var(--font-mono)' }}>−{d.deleted}</span>
                  </div>
                ))}
                {diffs.length > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--mut)', paddingTop: 8 }}>
                    Open full review to see line-by-line diffs and approve/reject per file.
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </DeskLayout>
  )
}

function ReviewTaskDetail({ taskId }: { taskId: string }) {
  const navigate = useNavigate()
  const [task, setTask] = useState<TDetail | null>(null)
  const [diffs, setDiffs] = useState<ReviewDiff[]>([])
  const [statuses, setStatuses] = useState<Record<string, FileStatus>>({})
  const [expanded, setExpanded] = useState<string | null>(null)
  const [diffText, setDiffText] = useState<Record<string, string>>({})
  // 'all' rejects every file still pending; a string rejects just that one.
  const [rejectTarget, setRejectTarget] = useState<'all' | string | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [doneMessage, setDoneMessage] = useState('')
  const [sending, setSending] = useState(false)
  // Defaults to true so the file-based controls don't flicker into a
  // task-level review while the first fetch is still in flight.
  const [hasRepo, setHasRepo] = useState(true)

  const load = useCallback(() => {
    fetchTask(taskId).then(setTask).catch(() => {})
    fetchReviewDiffs(taskId).then(r => {
      setDiffs(r.diffs)
      setHasRepo(r.has_repo)
    }).catch(() => {})
  }, [taskId])

  useEffect(() => { load() }, [load])

  const approvedFiles = Object.entries(statuses).filter(([, s]) => s === 'committed').map(([f]) => f)
  const pending = diffs.filter(d => statuses[d.file] !== 'committed')
  // Without a repo there are no files to gate on, and gating anyway is
  // exactly what used to strand these tasks in review permanently.
  const canAct = hasRepo ? pending.length > 0 : true

  const handleExpand = async (file: string) => {
    if (expanded === file) { setExpanded(null); return }
    setExpanded(file)
    if (!diffText[file]) {
      const res = await fetchReviewDiffText(taskId, file)
      setDiffText(prev => ({ ...prev, [file]: res.diff }))
    }
  }

  const handleApprove = async (file?: string) => {
    setError('')
    try {
      const res = await approveReview(taskId, file)
      setStatuses(prev => {
        const next = { ...prev }
        for (const d of file ? [file] : pending.map(p => p.file)) next[d] = 'committed'
        return next
      })
      if (res.task_status === 'done') {
        setDoneMessage(hasRepo
          ? 'Approved — every file committed, and the task moved to done.'
          : 'Approved — the task moved to done.')
      } else if (res.done_error) {
        setError(res.done_error)
      }
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Approve failed — the workspace may have changed branch. Refresh and retry.')
    }
  }

  const submitReject = async () => {
    if (!rejectTarget || !reason.trim()) return
    setSending(true)
    setError('')
    try {
      const file = rejectTarget === 'all' ? undefined : rejectTarget
      await rejectReview(taskId, reason.trim(), approvedFiles, file)
      navigate('/review')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reject failed')
      setSending(false)
    }
  }

  if (!task) return <DeskLayout scale="normal"><Card>Loading…</Card></DeskLayout>

  return (
    <DeskLayout scale="normal">
      <button onClick={() => navigate('/review')} style={{ color: 'var(--ink2)', fontSize: 13, marginBottom: 14 }}>← Review</button>

      {doneMessage && (
        <Card style={{ marginBottom: 16, border: '1px solid var(--ok)', background: 'var(--ok-soft)' }}>
          <span style={{ color: 'var(--ok)', fontSize: 13, fontWeight: 600 }}>✓ {doneMessage}</span>
        </Card>
      )}
      {error && (
        <Card style={{ marginBottom: 16, border: '1px solid var(--err)' }}>
          <span style={{ color: 'var(--err)', fontSize: 13 }}>{error}</span>
        </Card>
      )}

      <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
        {/* Left: task info */}
        <div style={{ width: 320, flexShrink: 0 }}>
          <Card>
            <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 8 }}>{task.title}</div>
            <Chip soft>{task.status}</Chip>
            {task.description && (
              <div style={{ fontSize: 12.5, color: 'var(--ink2)', marginTop: 12, whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                {task.description}
              </div>
            )}
            {task.acceptance_criteria.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <SectionLabel>Acceptance criteria</SectionLabel>
                {task.acceptance_criteria.map(c => (
                  <div key={c} style={{ fontSize: 12.5, color: 'var(--ink2)', padding: '4px 0' }}>
                    {task.criteria_met.includes(c) ? '✓' : '○'} {c}
                  </div>
                ))}
              </div>
            )}
            {task.progress.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <SectionLabel>Latest progress</SectionLabel>
                <div style={{ fontSize: 12, color: 'var(--ink2)', marginTop: 4, lineHeight: 1.5 }}>
                  {task.progress[task.progress.length - 1].entry}
                </div>
              </div>
            )}
          </Card>
        </div>

        {/* Right: file changes */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <Card>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <SectionLabel>
                {hasRepo ? `${pending.length} file${pending.length !== 1 ? 's' : ''} pending` : 'Task review'}
              </SectionLabel>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => { setRejectTarget('all'); setReason('') }}
                  disabled={!canAct}
                  style={{ padding: '6px 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, color: 'var(--err)', background: 'var(--card2)', opacity: canAct ? 1 : 0.5 }}
                >
                  {hasRepo ? 'Reject all' : 'Reject'}
                </button>
                <button
                  onClick={() => handleApprove()}
                  disabled={!canAct}
                  style={{ padding: '6px 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: canAct ? 1 : 0.5 }}
                >
                  {hasRepo ? 'Approve all' : 'Approve'}
                </button>
              </div>
            </div>

            {diffs.length === 0 && (
              <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.5 }}>
                {hasRepo
                  ? 'No pending changes.'
                  : "This workspace isn't a git repository, so there are no file diffs. Review the task's details and acceptance criteria on the left, then approve or reject."}
              </div>
            )}

            {diffs.map(d => {
              const committed = statuses[d.file] === 'committed'
              const isOpen = expanded === d.file
              return (
                <div key={d.file} style={{ borderBottom: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0' }}>
                    <span
                      onClick={() => handleExpand(d.file)}
                      style={{
                        flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12.5, cursor: 'pointer',
                        color: committed ? 'var(--mut)' : 'var(--ink)',
                        textDecoration: committed ? 'line-through' : undefined,
                      }}
                    >
                      {d.file}
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--ok)' }}>+{d.added}</span>
                    <span style={{ fontSize: 11, color: 'var(--err)' }}>−{d.deleted}</span>
                    {committed ? (
                      <Chip color="var(--ok)" soft>approved</Chip>
                    ) : (
                      <>
                        <button onClick={() => { setRejectTarget(d.file); setReason('') }} style={{ fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 6, background: 'var(--warn-soft)', color: 'var(--warn-ink)' }}>
                          Reject
                        </button>
                        <button onClick={() => handleApprove(d.file)} style={{ fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 6, background: 'var(--ok-soft)', color: 'var(--ok)' }}>
                          Approve
                        </button>
                      </>
                    )}
                  </div>
                  {isOpen && (
                    <pre style={{ marginBottom: 10, padding: 10, background: 'var(--mono-bg)', borderRadius: 8, fontSize: 11.5, fontFamily: 'var(--font-mono)', overflowX: 'auto', lineHeight: 1.5 }}>
                      {(diffText[d.file] || '').split('\n').map((line, i) => (
                        <div key={i} style={{ color: line.startsWith('+') ? 'var(--ok)' : line.startsWith('-') ? 'var(--err)' : 'var(--ink2)' }}>{line}</div>
                      ))}
                    </pre>
                  )}
                </div>
              )
            })}
          </Card>
        </div>
      </div>

      <Dialog open={rejectTarget !== null} onClose={() => setRejectTarget(null)} width={440}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4, color: 'var(--ink)' }}>
          Reject {rejectTarget === 'all' ? (hasRepo ? 'all remaining files' : 'this task') : rejectTarget}?
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', marginBottom: 14 }}>
          Nothing is discarded — the agent's session resumes with this feedback and keeps working.
          {approvedFiles.length > 0 && ` Already-approved files (${approvedFiles.join(', ')}) are mentioned as fine, so it knows not to touch them.`}
        </div>
        <Field label="Why">
          <textarea
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="What's wrong, and what should change…"
            rows={4}
            style={{ ...inputStyle, resize: 'vertical' }}
          />
        </Field>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button onClick={() => setRejectTarget(null)} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>
            Cancel
          </button>
          <button
            onClick={submitReject}
            disabled={!reason.trim() || sending}
            style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--err)', color: '#fff', opacity: reason.trim() && !sending ? 1 : 0.5 }}
          >
            Reject &amp; send back
          </button>
        </div>
      </Dialog>
    </DeskLayout>
  )
}

export default Review
