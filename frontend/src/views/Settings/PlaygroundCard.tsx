import { useCallback, useEffect, useState } from 'react'
import { Card, Chip, SectionLabel } from '../../components/primitives'
import ConfirmDialog from '../../components/ConfirmDialog'
import {
  createPlayground, fetchPlayground, resetPlayground, type PlaygroundStatus,
} from '../../lib/api'
import { accentTextBtnStyle } from './shared'

const STATUS_ORDER = ['done', 'review', 'in_progress', 'open', 'planned', 'draft', 'blocked']

/** The playground: a real half-built project you can stand up in one
 * click, so a fresh install has something to look at before you've
 * committed to setting a workspace up.
 *
 * It's a colour palette generator built with agent-knots, and the tasks
 * it arrives with are the genuine ones that built it — some done, one
 * waiting on review, some never started. Nothing here is a fixture. */
export function PlaygroundCard() {
  const [status, setStatus] = useState<PlaygroundStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)

  const load = useCallback(() => {
    fetchPlayground().then(setStatus).catch(() => {})
  }, [])
  useEffect(() => { load() }, [load])

  const handleCreate = async () => {
    setBusy(true)
    setError('')
    try {
      await createPlayground()
      load()
    } catch (e) {
      // Most likely cause by far is the clone failing — no network, or
      // the repo not reachable — so surface git's own words.
      setError(e instanceof Error ? e.message : 'Could not set up the playground')
    } finally {
      setBusy(false)
    }
  }

  const handleReset = async () => {
    setConfirmReset(false)
    setBusy(true)
    setError('')
    try {
      await resetPlayground()
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reset the playground')
    } finally {
      setBusy(false)
    }
  }

  if (status === null) return null

  const counts = Object.entries(status.task_counts)
    .sort((a, b) => STATUS_ORDER.indexOf(a[0]) - STATUS_ORDER.indexOf(b[0]))

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>Playground</SectionLabel>
        {!status.exists && (
          <button
            onClick={handleCreate}
            disabled={busy}
            style={accentTextBtnStyle({ marginLeft: 'auto', opacity: busy ? 0.6 : 1 })}
          >
            {busy ? 'Cloning…' : '+ Set up the playground'}
          </button>
        )}
      </div>

      <div style={{ fontSize: 11.5, color: 'var(--mut)', margin: '4px 0 14px', lineHeight: 1.5 }}>
        A half-built colour palette generator, built with agent-knots. The tasks it
        arrives with are the real ones that built it — some done, one waiting on
        review, some never started — so you can look around a project with actual
        history instead of an empty board.
      </div>

      {status.exists ? (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
            {counts.map(([s, n]) => <Chip key={s} mono soft>{n} {s.replace('_', ' ')}</Chip>)}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)', flex: 1, wordBreak: 'break-all' }}>
              {status.repository}
            </span>
            <button
              onClick={() => setConfirmReset(true)}
              disabled={busy}
              style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--err)', opacity: busy ? 0.6 : 1 }}
            >
              {busy ? 'Removing…' : 'Reset'}
            </button>
          </div>
        </>
      ) : (
        <div style={{ fontSize: 11, color: 'var(--mut)', wordBreak: 'break-all' }}>
          Clones from <code style={{ fontFamily: 'var(--font-mono)' }}>{status.repo}</code>
        </div>
      )}

      {error && (
        <div style={{ fontSize: 12, color: 'var(--err)', border: '1px solid var(--err)', padding: '8px 10px', borderRadius: 8, marginTop: 12, wordBreak: 'break-word' }}>
          {error}
        </div>
      )}

      <ConfirmDialog
        open={confirmReset}
        title="Reset the playground?"
        message={
          'This removes the playground workspace, all of its tasks, and its folder. ' +
          "Anything you changed in it is lost — but it's a demo, so you can set it up " +
          'again whenever you like.'
        }
        confirmLabel="Reset"
        danger
        onConfirm={handleReset}
        onCancel={() => setConfirmReset(false)}
      />
    </Card>
  )
}
