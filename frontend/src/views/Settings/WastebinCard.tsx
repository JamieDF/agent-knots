import { useEffect, useState } from 'react'
import { Card, SectionLabel, Chip } from '../../components/primitives'
import { fetchSettings, saveSettings, fetchWastebin, deleteWastebinEntry, type WastebinEntry } from '../../lib/api'
import { timeAgo } from '../../lib/format'

export function WastebinCard() {
  const [retentionDays, setRetentionDays] = useState<number | null>(null)
  const [entries, setEntries] = useState<WastebinEntry[]>([])
  const [saving, setSaving] = useState(false)

  const load = () => {
    fetchSettings().then(s => setRetentionDays(s.wastebin.retention_days)).catch(() => {})
    fetchWastebin().then(r => setEntries(r.entries)).catch(() => {})
  }

  useEffect(() => { load() }, [])

  const handleRetentionChange = async (days: number) => {
    setRetentionDays(days)
    setSaving(true)
    try {
      await saveSettings({
        default_model: '', api_key: '', base_url: '', default_mode: '',
        wastebin_retention_days: days,
      })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (sessionId: string) => {
    setEntries(prev => prev.filter(e => e.session_id !== sessionId))
    await deleteWastebinEntry(sessionId).catch(() => load())
  }

  if (retentionDays === null) return null

  return (
    <Card>
      <SectionLabel>Wastebin</SectionLabel>
      <div style={{ fontSize: 11.5, color: 'var(--mut)', margin: '4px 0 14px' }}>
        Every stopped agent session lands here — its git branch (if it survived) and any
        auto-provisioned working directory stay put until you delete the entry, or it ages out.
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ fontSize: 12.5, color: 'var(--ink2)' }}>Delete stopped sessions after</span>
        <input
          type="number"
          min={0}
          value={retentionDays}
          disabled={saving}
          onChange={e => handleRetentionChange(Math.max(0, parseInt(e.target.value, 10) || 0))}
          style={{
            width: 60, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--line2)',
            background: 'var(--card2)', color: 'var(--ink)', fontSize: 12.5, textAlign: 'center',
          }}
        />
        <span style={{ fontSize: 12.5, color: 'var(--ink2)' }}>days (0 = never)</span>
      </div>

      {entries.length === 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--mut)', textAlign: 'center', padding: '16px 0' }}>
          Nothing in the wastebin.
        </div>
      )}

      {entries.map(e => (
        <div
          key={e.session_id}
          style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0',
            borderBottom: '1px solid var(--line)',
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {e.task_title || e.session_id}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 2 }}>
              {e.advisory && <Chip soft>advisory{e.role ? ` · ${e.role}` : ''}</Chip>}
              {e.branch && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' }}>{e.branch}</span>}
              <span style={{ fontSize: 10.5, color: 'var(--mut)' }}>{timeAgo(e.stopped_at)}</span>
            </div>
          </div>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--mut)' }}>
            {e.tokens_used.toLocaleString()} tok · ${e.cost_usd.toFixed(3)}
          </span>
          <button
            onClick={() => handleDelete(e.session_id)}
            style={{ fontSize: 11.5, fontWeight: 600, padding: '3px 10px', borderRadius: 6, background: 'var(--card2)', color: 'var(--err)' }}
          >
            Delete
          </button>
        </div>
      ))}
    </Card>
  )
}
