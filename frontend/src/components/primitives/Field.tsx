import type { CSSProperties, ReactNode } from 'react'

/** Standard form-dialog input styling — was copy-pasted byte-for-byte
 * across TaskDialog, NewSessionDialog, WorkspaceDialog, SetupWizard,
 * Workflows, and Settings (found in a full-codebase review). Apply
 * directly to an <input>/<select>/<textarea>'s style prop. */
export const inputStyle: CSSProperties = {
  width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line2)',
  background: 'var(--card2)', color: 'var(--ink)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
}

interface Props {
  label: string
  hint?: string
  children: ReactNode
}

/** Labeled form field wrapper — same duplication as inputStyle above,
 * across the same six files. */
function Field({ label, hint, children }: Props) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <label style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--mut)' }}>{label}</label>
      {children}
      {hint && <span style={{ fontSize: 11, color: 'var(--mut)' }}>{hint}</span>}
    </div>
  )
}

export default Field
