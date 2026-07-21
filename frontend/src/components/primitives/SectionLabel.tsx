import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
}

/** Small uppercase section heading — "Section labels 10.5–11px 700
 * uppercase +.06em tracking" per the design tokens. */
function SectionLabel({ children }: Props) {
  return (
    <div
      style={{
        fontSize: 10.5,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        color: 'var(--mut)',
      }}
    >
      {children}
    </div>
  )
}

export default SectionLabel
