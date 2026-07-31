import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Toggle } from './primitives'
import { useNotifications } from '../lib/notifications'
import { fetchSettings, saveIntegrations } from '../lib/api'
import { timeAgo } from '../lib/format'
import { useClickOutside } from '../lib/useClickOutside'

/** Notification bell — pending-blocker count badge, dropdown of
 * blocker/done rows deep-linking to their task, and a phone-push
 * footer toggle. */
function NotificationBell() {
  const { items, blockerCount } = useNotifications()
  const [open, setOpen] = useState(false)
  const [phonePush, setPhonePush] = useState(false)
  const navigate = useNavigate()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => { fetchSettings().then(s => setPhonePush(s.integrations.phone_push)).catch(() => {}) }, [])

  useClickOutside(ref, open, () => setOpen(false))

  const handleTogglePush = async (checked: boolean) => {
    setPhonePush(checked)
    await saveIntegrations({ phone_push: checked })
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Notifications"
        style={{ position: 'relative', fontSize: 15, padding: '4px 6px', borderRadius: 8, color: 'var(--ink2)' }}
      >
        ◷
        {blockerCount > 0 && (
          <span style={{
            position: 'absolute', top: -2, right: -2, minWidth: 14, height: 14, borderRadius: 7,
            background: 'var(--warn-ink)', color: '#fff', fontSize: 9, fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 3px',
          }}>
            {blockerCount}
          </span>
        )}
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, marginTop: 8, width: 340,
          background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 12,
          boxShadow: 'var(--shadow-lg)', overflow: 'hidden', zIndex: 200,
        }}>
          <div style={{ maxHeight: 320, overflowY: 'auto' }}>
            {items.length === 0 && (
              <div style={{ padding: 20, textAlign: 'center', fontSize: 12.5, color: 'var(--mut)' }}>Nothing pending.</div>
            )}
            {items.map(i => (
              <div
                key={i.id}
                onClick={() => {
                  if (i.kind === 'question' && i.agentId) navigate(`/agent/${i.agentId}`)
                  else navigate(`/tasks/${i.taskId}`)
                  setOpen(false)
                }}
                style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '10px 14px', borderBottom: '1px solid var(--line)', cursor: 'pointer' }}
              >
                <span style={{ fontSize: 13, color: i.kind === 'blocker' ? 'var(--warn-ink)' : i.kind === 'question' ? 'var(--acc)' : 'var(--ok)', marginTop: 1 }}>
                  {i.kind === 'blocker' ? '⚠' : i.kind === 'question' ? '❓' : '✓'}
                </span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 12.5, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{i.title}</div>
                  <div style={{ fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>
                    {i.kind === 'question' ? 'agent question' : i.kind === 'blocker' ? 'blocked' : 'done'}
                    {i.agentName && <span> · {i.agentName}</span>}
                    {i.time > 0 && <span> · {timeAgo(i.time)}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderTop: '1px solid var(--line)' }}>
            <span style={{ fontSize: 11.5, color: 'var(--ink2)', flex: 1 }}>Push blockers to phone</span>
            <Toggle checked={phonePush} onChange={handleTogglePush} small />
          </div>
        </div>
      )}
    </div>
  )
}

export default NotificationBell
