import DeskLayout from '../components/DeskLayout'
import { Card } from '../components/primitives'

/** Placeholder — the real Review queue (pending diffs, approve/reject)
 * lands in Phase 4. See design_handoff_atelier_cockpit/README.md §5. */
function Review() {
  return (
    <DeskLayout width={850}>
      <Card>
        <div style={{ fontSize: 21, fontWeight: 600, marginBottom: 8 }}>Review</div>
        <div style={{ color: 'var(--mut)', fontSize: 13 }}>
          Coming soon — the pending-diff review queue.
        </div>
      </Card>
    </DeskLayout>
  )
}

export default Review
