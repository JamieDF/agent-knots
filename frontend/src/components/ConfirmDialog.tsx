import type { ReactNode } from 'react'
import { Dialog } from './primitives'

interface Props {
  open: boolean
  title: string
  message: string
  /** Extra controls between the message and the buttons — e.g. an
   * opt-in checkbox that changes what "confirm" actually does. */
  children?: ReactNode
  confirmLabel?: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Themed replacement for window.confirm() — destructive actions (delete
 * session, delete workspace, ...) get this instead of the browser's own
 * dialog, matching the rest of the app instead of looking like a
 * different program interrupted it. */
function ConfirmDialog({ open, title, message, children, confirmLabel = 'Confirm', danger, onConfirm, onCancel }: Props) {
  return (
    <Dialog open={open} onClose={onCancel} width={400}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 8, color: 'var(--ink)' }}>{title}</div>
      <div style={{ fontSize: 13, color: 'var(--ink2)', lineHeight: 1.5 }}>{message}</div>
      <div style={{ marginBottom: 20 }}>{children}</div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button
          onClick={onCancel}
          style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          autoFocus
          style={{
            padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600,
            background: danger ? 'var(--err)' : 'var(--acc)', color: '#fff',
          }}
        >
          {confirmLabel}
        </button>
      </div>
    </Dialog>
  )
}

export default ConfirmDialog
