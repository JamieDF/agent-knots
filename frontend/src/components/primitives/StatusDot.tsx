import { statusStyle } from '../../lib/statusColors'

interface Props {
  status: string
  size?: number
}

/** Colored glyph dot for a task/agent status, per the Atelier status map. */
function StatusDot({ status, size = 8 }: Props) {
  const { color, glyph } = statusStyle(status)
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: size + 4,
        height: size + 4,
        color,
        fontSize: size + 4,
        lineHeight: 1,
        flexShrink: 0,
      }}
      title={statusStyle(status).label}
    >
      {glyph}
    </span>
  )
}

export default StatusDot
