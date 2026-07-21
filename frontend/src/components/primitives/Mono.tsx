import type { CSSProperties, ReactNode } from 'react'

interface Props {
  children: ReactNode
  muted?: boolean
  style?: CSSProperties
}

/** Monospace text — ids, paths, tokens, timestamps, anything machine-y. */
function Mono({ children, muted, style }: Props) {
  return (
    <span
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: muted ? 'var(--mut)' : 'var(--ink2)',
        ...style,
      }}
    >
      {children}
    </span>
  )
}

export default Mono
