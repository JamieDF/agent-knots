import { useCallback, useEffect, useState } from 'react'
import { Card, Chip, SectionLabel, Toggle, inputStyle } from '../../components/primitives'
import { fetchPolicies, updatePolicy, type PolicyInfo } from '../../lib/api'

export function PoliciesCard() {
  const [policies, setPolicies] = useState<PolicyInfo[]>([])
  const load = useCallback(() => { fetchPolicies().then(d => setPolicies(d.policies)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  return (
    <Card>
      <SectionLabel>Policies</SectionLabel>
      <div style={{ fontSize: 11, color: 'var(--mut)', margin: '4px 0 10px' }}>
        Only the spend cap is actually enforced today — the rest are configured for later.
      </div>
      {policies.map(p => (
        <div key={p.key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{p.label}</div>
            <div style={{ fontSize: 11, color: 'var(--mut)' }}>{p.description}</div>
          </div>
          {p.key === 'spend_cap' && (
            <input
              aria-label="Spend cap value"
              value={p.value}
              onChange={e => setPolicies(prev => prev.map(x => x.key === p.key ? { ...x, value: e.target.value } : x))}
              onBlur={async e => { await updatePolicy(p.key, { value: e.target.value }); load() }}
              style={{ ...inputStyle, width: 70, textAlign: 'right' }}
            />
          )}
          {!p.enforced && <Chip soft color="var(--mut)">not enforced</Chip>}
          <Toggle checked={p.enabled} onChange={async checked => { await updatePolicy(p.key, { enabled: checked }); load() }} />
        </div>
      ))}
    </Card>
  )
}
