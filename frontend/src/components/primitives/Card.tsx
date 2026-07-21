import type { CSSProperties, ReactNode } from 'react'

interface Props {
  children: ReactNode
  raised?: boolean
  large?: boolean
  style?: CSSProperties
  className?: string
}

/** The base "floating card" surface from the Atelier design tokens —
 * white/dark card on the dot-grid desk background. */
function Card({ children, raised, large, style, className }: Props) {
  return (
    <div
      className={className}
      style={{
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: large ? 16 : 14,
        boxShadow: raised ? 'var(--shadow-lg)' : 'var(--shadow)',
        padding: large ? 18 : 14,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

export default Card
