import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
  color?: string
  soft?: boolean
  mono?: boolean
  onClick?: () => void
}

/** Small rounded label — status/priority badges, tags, id chips. */
function Chip({ children, color = 'var(--ink2)', soft, mono, onClick }: Props) {
  return (
    <span
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 8,
        fontSize: 9.5,
        fontWeight: 600,
        textTransform: soft ? 'uppercase' : undefined,
        letterSpacing: soft ? '0.04em' : undefined,
        fontFamily: mono ? 'var(--font-mono)' : undefined,
        color: soft ? color : 'var(--ink2)',
        background: soft ? colorSoftBg(color) : 'var(--card2)',
        cursor: onClick ? 'pointer' : undefined,
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  )
}

function colorSoftBg(color: string): string {
  // Atelier's soft chips use each semantic color's dedicated -soft token
  // where one exists; fall back to the card2 surface otherwise.
  if (color === 'var(--acc)') return 'var(--acc-soft)'
  if (color === 'var(--ok)') return 'var(--ok-soft)'
  if (color === 'var(--warn)' || color === 'var(--warn-ink)') return 'var(--warn-soft)'
  return 'var(--card2)'
}

export default Chip
