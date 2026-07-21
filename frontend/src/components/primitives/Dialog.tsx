import { useEffect, type ReactNode } from 'react'

interface Props {
  open: boolean
  onClose: () => void
  children: ReactNode
  width?: number
}

/** Fixed-position overlay + centered card, matching the prototype's
 * dialog pattern (task create/edit, new session, custom tool, workspace,
 * role config) — layered over whatever screen is currently showing,
 * closable via Escape or backdrop click. */
function Dialog({ open, onClose, children, width = 480 }: Props) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(20, 20, 30, 0.45)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width,
          maxWidth: '90vw',
          maxHeight: '85vh',
          overflowY: 'auto',
          background: 'var(--card)',
          border: '1px solid var(--line)',
          borderRadius: 16,
          boxShadow: 'var(--shadow-lg)',
          padding: 20,
        }}
      >
        {children}
      </div>
    </div>
  )
}

export default Dialog
