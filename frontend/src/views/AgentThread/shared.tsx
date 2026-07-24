/** The small status-bar strip at the top of each right-rail panel
 * (Terminal/Files/Commands) — was copy-pasted across all three. */
export function PanelHeader({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: '6px 10px', fontSize: 10, color: 'var(--mut)', borderBottom: '1px solid var(--line)', fontFamily: 'var(--font-mono)' }}>
      {children}
    </div>
  )
}

/** The "nothing here yet" message shown below an empty PanelHeader —
 * same duplication as PanelHeader above. */
export function PanelEmptyState({ children }: { children: React.ReactNode }) {
  return <div style={{ padding: 12, fontSize: 12, color: 'var(--mut)' }}>{children}</div>
}
