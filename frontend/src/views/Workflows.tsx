import DeskLayout from '../components/DeskLayout'
import { Card } from '../components/primitives'

/** Placeholder — stage config, default agent roles, and the generated
 * workflow diagram land in Phase 4. See
 * design_handoff_atelier_cockpit/README.md §6. */
function Workflows() {
  return (
    <DeskLayout width={850}>
      <Card>
        <div style={{ fontSize: 21, fontWeight: 600, marginBottom: 8 }}>Workflows</div>
        <div style={{ color: 'var(--mut)', fontSize: 13 }}>
          Coming soon — board stage config and default agent roles.
        </div>
      </Card>
    </DeskLayout>
  )
}

export default Workflows
