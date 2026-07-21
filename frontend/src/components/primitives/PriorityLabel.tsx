import { priorityColor } from '../../lib/priorityColors'

interface Props {
  priority: string
}

/** Uppercase priority label in its semantic color. */
function PriorityLabel({ priority }: Props) {
  return (
    <span
      style={{
        fontSize: 10.5,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        color: priorityColor(priority),
      }}
    >
      {priority}
    </span>
  )
}

export default PriorityLabel
