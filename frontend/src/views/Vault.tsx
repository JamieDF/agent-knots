import { useEffect, useState, useCallback } from 'react'
import DeskLayout from '../components/DeskLayout'
import { Card, Chip, Dialog } from '../components/primitives'
import {
  fetchVaultStatus, unlockVault, lockVault,
  fetchCredentials, addCredential, deleteCredential, fetchAuditLog,
  type CredentialInfo, type AuditEntryInfo,
} from '../lib/api'

/** VaultStore's AuditEntry has no explicit action field — every
 * successful call (add, use) logs the same shape, distinguished only
 * by whether a command/template was involved. This is a best-effort
 * label from what's actually determinable, not a literal action enum;
 * VaultStore itself is well-tested existing code, so this reads its
 * data rather than asking it to log more precisely. */
function auditAction(e: { success: boolean; command: string }): { label: string; color: string } {
  if (!e.success) return { label: 'ERROR', color: 'var(--err)' }
  if (e.command) return { label: 'INJECT', color: 'var(--acc)' }
  return { label: 'ACCESS', color: 'var(--warn-ink)' }
}

function templateChips(c: CredentialInfo): string[] {
  const chips: string[] = []
  for (const t of c.templates) {
    for (const key of Object.keys(t.env)) chips.push(`env:${key}`)
    if (t.file_path) chips.push(`file:${t.file_path}`)
    if (t.command_wrapper) chips.push('wrapper')
  }
  return chips
}

function timeAgo(ts: number): string {
  if (!ts) return 'never'
  const s = Date.now() / 1000 - ts
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/** Vault screen — locked/unlocked states, credentials list, audit log.
 * Values never reach this component; the API only ever returns
 * metadata. See design_handoff_atelier_cockpit/README.md §7. */
function Vault() {
  const [lockState, setLockState] = useState<'locked' | 'unlocked' | 'uninitialized' | null>(null)
  const [passphrase, setPassphrase] = useState('')
  const [unlockError, setUnlockError] = useState('')
  const [unlocking, setUnlocking] = useState(false)

  const [credentials, setCredentials] = useState<CredentialInfo[]>([])
  const [audit, setAudit] = useState<AuditEntryInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)

  const loadStatus = useCallback(async () => {
    const s = await fetchVaultStatus()
    setLockState(s.lock_state)
    return s.lock_state
  }, [])

  const loadUnlockedData = useCallback(async () => {
    const [c, a] = await Promise.all([fetchCredentials(), fetchAuditLog()])
    setCredentials(c.credentials)
    setAudit(a.entries)
  }, [])

  useEffect(() => {
    loadStatus().then(state => { if (state === 'unlocked') loadUnlockedData() })
  }, [loadStatus, loadUnlockedData])

  const handleUnlock = async () => {
    setUnlocking(true); setUnlockError('')
    try {
      await unlockVault(passphrase)
      setPassphrase('')
      await loadStatus()
      await loadUnlockedData()
    } catch (e) {
      setUnlockError(e instanceof Error ? e.message : 'Failed to unlock')
    } finally {
      setUnlocking(false)
    }
  }

  const handleLock = async () => {
    await lockVault()
    setCredentials([]); setAudit([])
    await loadStatus()
  }

  const handleDelete = async (id: string) => {
    await deleteCredential(id)
    loadUnlockedData()
  }

  if (lockState === null) return <DeskLayout width={420}><Card>Loading…</Card></DeskLayout>

  if (lockState !== 'unlocked') {
    return (
      <DeskLayout width={420}>
        <Card>
          <div style={{ textAlign: 'center', padding: '8px 0 4px' }}>
            <div style={{
              width: 56, height: 56, borderRadius: 14, background: 'var(--card2)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 26, margin: '0 auto 14px',
            }}>🔒</div>
            <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>
              {lockState === 'uninitialized' ? 'Set up the vault' : 'Vault is locked'}
            </div>
            <div style={{ fontSize: 12, color: 'var(--mut)', marginBottom: 18 }}>
              AES-256-GCM encrypted credential store
            </div>
            <input
              type="password"
              aria-label="Passphrase"
              value={passphrase}
              onChange={e => setPassphrase(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleUnlock()}
              placeholder="Passphrase"
              style={{ ...inputStyle, marginBottom: 12, textAlign: 'center' }}
              autoFocus
            />
            {unlockError && <div style={{ fontSize: 11.5, color: 'var(--err)', marginBottom: 10 }}>{unlockError}</div>}
            <button
              onClick={handleUnlock}
              disabled={unlocking || !passphrase}
              style={{
                width: '100%', padding: '9px 14px', borderRadius: 8, fontSize: 13, fontWeight: 700,
                background: 'var(--acc)', color: 'var(--acc-ink)', opacity: unlocking || !passphrase ? 0.6 : 1,
              }}
            >
              {unlocking ? 'Unlocking…' : lockState === 'uninitialized' ? 'Create vault' : 'Unlock vault'}
            </button>
          </div>
        </Card>
      </DeskLayout>
    )
  }

  return (
    <DeskLayout width={900}>
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>Credentials</div>
          <Chip color="var(--ok)" soft>UNLOCKED</Chip>
          <button onClick={handleLock} style={{ fontSize: 12, fontWeight: 600, color: 'var(--acc)' }}>Lock</button>
          <div style={{ marginLeft: 'auto' }}>
            <button
              onClick={() => setShowAdd(true)}
              style={{ padding: '6px 14px', borderRadius: 8, fontSize: 12.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)' }}
            >
              + Add credential
            </button>
          </div>
        </div>

        {credentials.length === 0 && (
          <div style={{ textAlign: 'center', padding: 20, color: 'var(--mut)', fontSize: 13 }}>No credentials yet.</div>
        )}

        {credentials.map(c => (
          <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 0', borderBottom: '1px solid var(--line)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--ink)', minWidth: 100 }}>{c.id}</span>
            <span style={{ fontSize: 11.5, color: 'var(--mut)', flex: 1 }}>{c.description}</span>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {templateChips(c).map((t, i) => <Chip key={i} mono>{t}</Chip>)}
            </div>
            <span style={{ fontSize: 10.5, color: 'var(--mut)', minWidth: 70, textAlign: 'right' }}>{timeAgo(c.last_used)}</span>
            <button onClick={() => handleDelete(c.id)} style={{ color: 'var(--err)', fontSize: 14 }}>✕</button>
          </div>
        ))}
      </Card>

      <Card>
        <div style={{ marginBottom: 10, fontSize: 15, fontWeight: 700 }}>Audit log</div>
        {audit.length === 0 && (
          <div style={{ textAlign: 'center', padding: 16, color: 'var(--mut)', fontSize: 13 }}>No activity yet.</div>
        )}
        {audit.map((e, i) => {
          const action = auditAction(e)
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '6px 0', borderBottom: '1px solid var(--line)', fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>
              <span style={{ color: 'var(--mut)', minWidth: 130 }}>{new Date(e.timestamp * 1000).toLocaleString()}</span>
              <span style={{ color: action.color, fontWeight: 700, minWidth: 60 }}>{action.label}</span>
              <span style={{ color: 'var(--ink)', flex: 1 }}>{e.credential}</span>
              <span style={{ color: 'var(--mut)' }}>{e.caller}</span>
            </div>
          )
        })}
      </Card>

      <AddCredentialDialog
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onSaved={() => { setShowAdd(false); loadUnlockedData() }}
      />
    </DeskLayout>
  )
}

function AddCredentialDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [id, setId] = useState('')
  const [description, setDescription] = useState('')
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const reset = () => { setId(''); setDescription(''); setValue(''); setError('') }

  const handleSave = async () => {
    if (!id.trim() || !value) return
    setSaving(true); setError('')
    try {
      await addCredential({ id: id.trim(), description, value })
      reset()
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add credential')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={() => { reset(); onClose() }} width={420}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>+ Add credential</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="ID">
          <input aria-label="Credential ID" value={id} onChange={e => setId(e.target.value)} placeholder="github" style={inputStyle} />
        </Field>
        <Field label="Description">
          <input aria-label="Description" value={description} onChange={e => setDescription(e.target.value)} placeholder="optional" style={inputStyle} />
        </Field>
        <Field label="Value">
          <input aria-label="Value" type="password" value={value} onChange={e => setValue(e.target.value)} placeholder="ghp_xxx" style={inputStyle} />
        </Field>
        {error && <div style={{ fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={() => { reset(); onClose() }} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
          <button onClick={handleSave} disabled={saving || !id.trim() || !value} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)', opacity: saving || !id.trim() || !value ? 0.6 : 1 }}>
            {saving ? 'Adding…' : 'Add'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <label style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--mut)' }}>{label}</label>
      {children}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line2)',
  background: 'var(--card2)', color: 'var(--ink)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
}

export default Vault
