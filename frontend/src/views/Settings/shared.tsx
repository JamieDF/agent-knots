import { Dialog } from '../../components/primitives'

// The delete-"✕" and small accent-text ("+ Add X", "Lock") button
// styles were copy-pasted 6x/5x across this file's section cards —
// AgentThread.tsx already extracted an equivalent pillBtn() helper for
// the same problem, this file never got the same treatment.
export const deleteBtnStyle: React.CSSProperties = { color: 'var(--err)', fontSize: 14 }
export function accentTextBtnStyle(extra?: React.CSSProperties): React.CSSProperties {
  return { fontSize: 12, fontWeight: 600, color: 'var(--acc)', ...extra }
}

// AddProviderDialog/CustomToolDialog/AddCredentialDialog were three
// near-identical "title + Field stack + error + Cancel/Save footer"
// dialogs, differing only in their fields and one preset-chips row
// (AddProviderDialog only, passed via headerExtra). Each dialog still
// owns its own field state and save logic — only the wrapper chrome
// (title, error slot, footer buttons, saving/disabled states) is shared.
export function FormDialog({
  open, onClose, title, width = 440, headerExtra, children,
  onSave, saveDisabled, saving, error, saveLabel = 'Add', savingLabel = 'Adding…',
}: {
  open: boolean
  onClose: () => void
  title: string
  width?: number
  headerExtra?: React.ReactNode
  children: React.ReactNode
  onSave: () => void
  saveDisabled?: boolean
  saving: boolean
  error: string
  saveLabel?: string
  savingLabel?: string
}) {
  return (
    <Dialog open={open} onClose={onClose} width={width}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>{title}</div>
      {headerExtra}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {children}
        {error && <div style={{ fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={onClose} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
          <button onClick={onSave} disabled={saving || saveDisabled} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: saving || saveDisabled ? 0.6 : 1 }}>
            {saving ? savingLabel : saveLabel}
          </button>
        </div>
      </div>
    </Dialog>
  )
}
