import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import DeskLayout from '../components/DeskLayout'
import { Card, Chip, SectionLabel, Dialog, Field, inputStyle } from '../components/primitives'
import {
  fetchReviewTasks, fetchReviewDiffs, fetchReviewDiffText, approveReview, rejectReview, fetchTask,
  type ReviewTask, type ReviewDiff, type TaskDetail as TDetail,
} from '../lib/api'

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

  const load = useCallback(() => {
    fetchReviewTasks().then(r => setTasks(r.tasks)).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [load])

  return (
    <DeskLayout width={850}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <div style={{ fontSize: 18, fontWeight: 700 }}>Review</div>
        <Chip color="var(--warn-ink)" soft>{tasks.length} waiting</Chip>
      </div>

      {tasks.length === 0 && (
        <Card><div style={{ textAlign: 'center', padding: 20, color: 'var(--mut)', fontSize: 13 }}>Nothing waiting on review.</div></Card>
      )}

      {tasks.map(t => (
        <div key={t.id} onClick={() => navigate(`/review/${t.id}`)} style={{ cursor: 'pointer', marginBottom: 10 }}>
          <Card>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--ink)', flex: 1 }}>{t.title}</span>
              {t.project_name && <Chip mono>{t.project_name}</Chip>}
            </div>
            <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 6, fontFamily: 'var(--font-mono)' }}>
              {t.branch}{t.session_name && ` · ${t.session_name}`}
            </div>
          </Card>
        </div>
      ))}
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

  const load = useCallback(() => {
    fetchTask(taskId).then(setTask).catch(() => {})
    fetchReviewDiffs(taskId).then(r => setDiffs(r.diffs)).catch(() => {})
  }, [taskId])

  useEffect(() => { load() }, [load])

  const approvedFiles = Object.entries(statuses).filter(([, s]) => s === 'committed').map(([f]) => f)
  const pending = diffs.filter(d => statuses[d.file] !== 'committed')

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
        setDoneMessage('Approved — every file committed, and the task moved to done.')
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

  if (!task) return <DeskLayout width={1040}><Card>Loading…</Card></DeskLayout>

  return (
    <DeskLayout width={1040}>
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
              <SectionLabel>{pending.length} file{pending.length !== 1 ? 's' : ''} pending</SectionLabel>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => { setRejectTarget('all'); setReason('') }}
                  disabled={pending.length === 0}
                  style={{ padding: '6px 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, color: 'var(--err)', background: 'var(--card2)', opacity: pending.length === 0 ? 0.5 : 1 }}
                >
                  Reject all
                </button>
                <button
                  onClick={() => handleApprove()}
                  disabled={pending.length === 0}
                  style={{ padding: '6px 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: pending.length === 0 ? 0.5 : 1 }}
                >
                  Approve all
                </button>
              </div>
            </div>

            {diffs.length === 0 && <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>No pending changes.</div>}

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
          Reject {rejectTarget === 'all' ? 'all remaining files' : rejectTarget}?
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
