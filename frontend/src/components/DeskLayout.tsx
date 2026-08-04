import { forwardRef, type ReactNode } from 'react'

type Scale = 'narrow' | 'normal' | 'wide'

// Each scale is a multiplier on the base --content-width CSS variable.
// Kept tight (±5%) so switching tabs doesn't jarringly resize — the
// Board gets a touch more room for its kanban columns, focused screens
// a touch less, but they're all visibly the same column.
const SCALE_MULTIPLIER: Record<Scale, number> = {
  narrow: 0.95,
  normal: 1.0,
  wide: 1.08,
}

interface Props {
  children: ReactNode
  scale?: Scale
}

/** The dotted-grid "desk" background + centered-column page scaffold used
 * by every Atelier screen. Width is driven by the --content-width CSS
 * variable (responsive + customizable) times a per-view scale factor.
 * Forwards a ref to the scrollable outer div so pages with in-page
 * navigation (Settings) can scroll-spy / scrollIntoView within it. */
const DeskLayout = forwardRef<HTMLDivElement, Props>(function DeskLayout({ children, scale = 'normal' }, ref) {
  const maxWidth = `calc(var(--content-width) * ${SCALE_MULTIPLIER[scale]})`
  return (
    <div
      ref={ref}
      style={{
        flex: 1,
        overflowY: 'auto',
        background: `
          radial-gradient(var(--dot) 1px, transparent 1px)
        `,
        backgroundSize: '22px 22px',
        backgroundColor: 'var(--bg)',
      }}
    >
      <div
        style={{
          maxWidth,
          margin: '0 auto',
          padding: '28px 20px 60px',
        }}
      >
        {children}
      </div>
    </div>
  )
})

export default DeskLayout
