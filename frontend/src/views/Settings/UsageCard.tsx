import { useEffect, useState } from 'react'
import { Card, SectionLabel } from '../../components/primitives'
import { fetchUsage, type UsageSummary } from '../../lib/api'

export function UsageCard() {
  const [usage, setUsage] = useState<UsageSummary | null>(null)

  useEffect(() => { fetchUsage().then(setUsage).catch(() => {}) }, [])

  if (!usage) return null

  const maxProviderTokens = Math.max(1, ...usage.by_provider.map(p => p.tokens))
  const maxTaskTokens = Math.max(1, ...usage.top_tasks.map(t => t.tokens))

  return (
    <Card>
      <SectionLabel>Usage</SectionLabel>
      <div style={{ fontSize: 11.5, color: 'var(--mut)', margin: '4px 0 14px' }}>
        Token counts are exact; cost is an estimate from each provider's pricing.
      </div>
      <div style={{ display: 'flex', gap: 24, marginBottom: 16 }}>
        <Stat label="Tokens today" value={usage.today.tokens.toLocaleString()} />
        <Stat label="Tokens this month" value={usage.month.tokens.toLocaleString()} />
        <Stat label="~$ today" value={`$${usage.today.cost_usd.toFixed(2)}`} />
        <Stat label="~$ this month" value={`$${usage.month.cost_usd.toFixed(2)}`} />
      </div>

      {usage.by_provider.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--mut)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>By provider</div>
          {usage.by_provider.map(p => (
            <BarRow key={p.provider} label={p.provider} value={p.tokens} max={maxProviderTokens} suffix={`${p.tokens.toLocaleString()} tok · ~$${p.cost_usd.toFixed(2)}`} />
          ))}
        </div>
      )}

      {usage.top_tasks.length > 0 && (
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--mut)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Top tasks by tokens</div>
          {usage.top_tasks.map(t => (
            <BarRow key={t.task_id} label={t.task_id} value={t.tokens} max={maxTaskTokens} suffix={`${t.tokens.toLocaleString()} tok`} />
          ))}
        </div>
      )}
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--ink)' }}>{value}</div>
      <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>{label}</div>
    </div>
  )
}

function BarRow({ label, value, max, suffix }: { label: string; value: number; max: number; suffix: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0' }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink2)', minWidth: 90 }}>{label}</span>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--card2)', overflow: 'hidden' }}>
        <div style={{ width: `${Math.max(2, (value / max) * 100)}%`, height: '100%', background: 'var(--acc)' }} />
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)', minWidth: 120, textAlign: 'right' }}>{suffix}</span>
    </div>
  )
}
