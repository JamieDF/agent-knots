import DeskLayout from '../components/DeskLayout'
import { Card } from '../components/primitives'

/** Placeholder — real vault web routes + UI land in Phase 5. See
 * design_handoff_atelier_cockpit/README.md §7. */
function Vault() {
  return (
    <DeskLayout width={850}>
      <Card>
        <div style={{ fontSize: 21, fontWeight: 600, marginBottom: 8 }}>Vault</div>
        <div style={{ color: 'var(--mut)', fontSize: 13 }}>
          Coming soon — encrypted credential store, unlocked from the cockpit.
        </div>
      </Card>
    </DeskLayout>
  )
}

export default Vault
