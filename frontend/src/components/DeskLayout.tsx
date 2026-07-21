import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
  width?: 420 | 800 | 850 | 880 | 900 | 1000 | 1240 | 1280
}

/** The dotted-grid "desk" background + centered-column page scaffold used
 * by every Atelier screen. Width follows the per-screen values from the
 * design handoff (Dashboard 850, Task Detail 880, Tasks list 1000, board
 * 1240, Thread 1280, Vault locked 420 / unlocked 900, Settings 800). */
function DeskLayout({ children, width = 850 }: Props) {
  return (
    <div
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
          maxWidth: width,
          margin: '0 auto',
          padding: '28px 20px 60px',
        }}
      >
        {children}
      </div>
    </div>
  )
}

export default DeskLayout
