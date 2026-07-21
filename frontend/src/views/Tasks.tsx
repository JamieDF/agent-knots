import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import DeskLayout from '../components/DeskLayout'
import Board from './tasks/Board'
import List from './tasks/List'
import TaskDialog from '../components/TaskDialog'

/** Tasks screen shell — Board/List tab pill + "+ New task" + "⚙ Stages"
 * header, per design_handoff_atelier_cockpit/README.md §3. Stage config
 * (the "⚙ Stages" button) lives on the Workflows screen (Phase 4) — for
 * now it just links there. */
function Tasks() {
  const [searchParams, setSearchParams] = useSearchParams()
  const view = searchParams.get('view') === 'list' ? 'list' : 'board'
  const [showCreate, setShowCreate] = useState(false)
  const navigate = useNavigate()

  const setView = (v: 'board' | 'list') => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('view', v)
      return next
    })
  }

  return (
    <DeskLayout width={view === 'board' ? 1240 : 1000}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 2, padding: 3, borderRadius: 10, background: 'var(--card2)' }}>
          {(['board', 'list'] as const).map(v => (
            <button
              key={v}
              onClick={() => setView(v)}
              style={{
                padding: '5px 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600,
                textTransform: 'capitalize',
                background: view === v ? 'var(--card)' : 'transparent',
                color: view === v ? 'var(--ink)' : 'var(--ink2)',
                boxShadow: view === v ? 'var(--shadow)' : undefined,
              }}
            >
              {v}
            </button>
          ))}
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button
            onClick={() => navigate('/workflows')}
            style={{ padding: '6px 12px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}
          >
            ⚙ Stages
          </button>
          <button
            onClick={() => setShowCreate(true)}
            style={{ padding: '6px 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)' }}
          >
            + New task
          </button>
        </div>
      </div>

      {view === 'board' ? <Board /> : <List />}

      <TaskDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onSaved={() => setShowCreate(false)}
      />
    </DeskLayout>
  )
}

export default Tasks
