import { useEffect, useState, useCallback } from 'react'
import DeskLayout from '../components/DeskLayout'
import { Card, Chip } from '../components/primitives'
import { fetchReviewDiffs, fetchReviewDiffText, approveReview, rejectReview, type ReviewDiff } from '../lib/api'

type Status = 'pending' | 'committed' | 'rejected'

/** Review queue — pending diffs derived live from git (post-hoc, no
 * separate capture/staging layer, per WORKPLAN.md's Phase 4 decoupling
 * note). See design_handoff_atelier_cockpit/README.md §5. */
function Review() {
  const [diffs, setDiffs] = useState<ReviewDiff[]>([])
  const [statuses, setStatuses] = useState<Record<string, Status>>({})
  const [expanded, setExpanded] = useState<string | null>(null)
  const [diffText, setDiffText] = useState<Record<string, string>>({})
  const [conflict, setConflict] = useState('')

  const key = (d: ReviewDiff) => `${d.workspace}:${d.file}`

  const load = useCallback(async () => {
    const res = await fetchReviewDiffs()
    setDiffs(res.diffs)
  }, [])

  useEffect(() => { load() }, [load])

  const handleExpand = async (d: ReviewDiff) => {
    const k = key(d)
    if (expanded === k) { setExpanded(null); return }
    setExpanded(k)
    if (!diffText[k]) {
      const res = await fetchReviewDiffText(d.workspace, d.file)
      setDiffText(prev => ({ ...prev, [k]: res.diff }))
    }
  }

  const handleApprove = async (d: ReviewDiff) => {
    try {
      await approveReview(d.workspace, d.file, d.branch)
      setStatuses(prev => ({ ...prev, [key(d)]: 'committed' }))
    } catch (e) {
      setConflict(e instanceof Error ? e.message : 'Approve failed — the workspace may have changed branch. Refresh and retry.')
    }
  }

  const handleReject = async (d: ReviewDiff) => {
    await rejectReview(d.workspace, d.file)
    setStatuses(prev => ({ ...prev, [key(d)]: 'rejected' }))
  }

  const handleApproveAll = async () => {
    const byWorkspace = new Map<string, ReviewDiff[]>()
    for (const d of diffs) {
      if (statuses[key(d)]) continue
      const list = byWorkspace.get(d.workspace) || []
      list.push(d)
      byWorkspace.set(d.workspace, list)
    }
    for (const [workspace, items] of byWorkspace) {
      // Every diff in one workspace's listing shares the same branch —
      // they all came from the same git-status snapshot of that repo.
      try {
        await approveReview(workspace, undefined, items[0]?.branch)
        setStatuses(prev => {
          const next = { ...prev }
          for (const d of items) next[key(d)] = 'committed'
          return next
        })
      } catch (e) {
        setConflict(e instanceof Error ? e.message : 'Approve failed — the workspace may have changed branch. Refresh and retry.')
      }
    }
  }

  const pending = diffs.filter(d => !statuses[key(d)])

  return (
    <DeskLayout width={850}>
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>Review</div>
          <Chip color="var(--warn-ink)" soft>{pending.length} pending</Chip>
          <div style={{ marginLeft: 'auto' }}>
            <button
              onClick={handleApproveAll}
              disabled={pending.length === 0}
              style={{ padding: '6px 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: pending.length === 0 ? 0.5 : 1 }}
            >
              Approve all
            </button>
          </div>
        </div>
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 8 }}>
          Pending diffs are each workspace's current uncommitted git changes, on whichever branch is currently checked out there. Approve stages and commits the file; reject only acknowledges — it never discards your changes. If a different session takes over the workspace and switches branches before you approve, you'll be asked to refresh.
        </div>
      </Card>

      {conflict && (
        <Card style={{ marginBottom: 16, border: '1px solid var(--warn)', background: 'var(--warn-soft)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 12.5, color: 'var(--warn-ink)' }}>⚠ {conflict}</span>
            <button
              onClick={() => { setConflict(''); load() }}
              style={{ fontSize: 11.5, fontWeight: 600, padding: '3px 10px', borderRadius: 6, background: 'var(--warn)', color: 'var(--acc-ink)', whiteSpace: 'nowrap' }}
            >
              Refresh
            </button>
          </div>
        </Card>
      )}

      {diffs.length === 0 && (
        <Card><div style={{ textAlign: 'center', padding: 20, color: 'var(--mut)', fontSize: 13 }}>Nothing to review.</div></Card>
      )}

      {diffs.map(d => {
        const k = key(d)
        const status = statuses[k]
        return (
          <Card key={k} style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }} onClick={() => handleExpand(d)}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--ink)', flex: 1 }}>{d.file}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ok)' }}>+{d.added}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--err)' }}>−{d.deleted}</span>
              <span style={{ fontSize: 11, color: 'var(--mut)' }}>{d.workspace_name}</span>
              {d.branch && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)', padding: '2px 6px', borderRadius: 5, background: 'var(--card2)' }}>{d.branch}</span>}
              {status === 'committed' && <Chip color="var(--ok)" soft>Approved — committed</Chip>}
              {status === 'rejected' && <Chip color="var(--err)" soft>Rejected — agent notified</Chip>}
              {!status && (
                <div style={{ display: 'flex', gap: 6 }} onClick={e => e.stopPropagation()}>
                  <button onClick={() => handleApprove(d)} style={{ fontSize: 11.5, fontWeight: 600, padding: '3px 10px', borderRadius: 6, background: 'var(--ok-soft)', color: 'var(--ok)' }}>✓ Approve</button>
                  <button onClick={() => handleReject(d)} style={{ fontSize: 11.5, fontWeight: 600, padding: '3px 10px', borderRadius: 6, background: 'var(--warn-soft)', color: 'var(--warn-ink)' }}>✕ Reject</button>
                </div>
              )}
            </div>
            {expanded === k && (
              <pre style={{ marginTop: 10, padding: 10, background: 'var(--mono-bg)', borderRadius: 8, fontSize: 11.5, fontFamily: 'var(--font-mono)', overflowX: 'auto', lineHeight: 1.5 }}>
                {(diffText[k] || '').split('\n').map((line, i) => (
                  <div key={i} style={{ color: line.startsWith('+') ? 'var(--ok)' : line.startsWith('-') ? 'var(--err)' : 'var(--ink2)' }}>{line}</div>
                ))}
              </pre>
            )}
          </Card>
        )
      })}
    </DeskLayout>
  )
}

export default Review
