import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import DeskLayout from '../components/DeskLayout'
import { Card, Chip, Toggle, SectionLabel, Dialog, Field, inputStyle } from '../components/primitives'
import {
  fetchStages, toggleStage, fetchRoles, updateRole, fetchSettings,
  type StageInfo, type RoleInfo, type ProviderInfo,
} from '../lib/api'

const TRIGGER_LABELS: Record<string, string> = {
  leaves_draft: 'leaves draft',
  is_started: 'is started',
  enters_review: 'enters review',
  manual: 'manual',
}

const TRIGGER_TO_STAGE: Record<string, string> = {
  leaves_draft: 'draft',
  is_started: 'in_progress',
  enters_review: 'review',
}

const PIPELINE_TEMPLATES = [
  { name: 'Plan → Code → Review', description: 'Planner drafts the task, Builder works it, Reviewer checks it before done.' },
  { name: 'Code → Review', description: 'Skip planning — Builder works the task as-is, Reviewer checks it.' },
  { name: 'Security sweep', description: 'A read-only security-focused pass over a task, no code changes.' },
]

/** Workflows screen — stage config, default agent roles, generated
 * workflow diagram, pipeline templates. */
function Workflows() {
  const [stages, setStages] = useState<StageInfo[]>([])
  const [roles, setRoles] = useState<RoleInfo[]>([])
  const [configuring, setConfiguring] = useState<RoleInfo | null>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    const [s, r] = await Promise.all([fetchStages(), fetchRoles()])
    setStages(s.stages)
    setRoles(r.roles)
  }, [])

  useEffect(() => { load() }, [load])

  const handleToggleStage = async (key: string, enabled: boolean) => {
    try {
      const res = await toggleStage(key, enabled)
      setStages(res.stages)
    } catch { /* required stage — ignore, UI already reflects real state on next load */ }
  }

  return (
    <DeskLayout scale="narrow">
      {/* Current workflow diagram */}
      <Card style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 12 }}><SectionLabel>Current workflow</SectionLabel></div>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 4, flexWrap: 'wrap' }}>
          {stages.filter(s => s.enabled).map((s, i, arr) => (
            <div key={s.key} style={{ display: 'flex', alignItems: 'flex-start', gap: 4 }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, minWidth: 100 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--mut)' }} />
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--ink)' }}>{s.label}</span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--mut)', textAlign: 'center' }}>
                  {s.key === 'in_progress' ? 'blocked waits here' : s.key === 'done' ? 'criteria gated' : 'you or ✨ agent drafts'}
                </div>
                {roles.filter(r => r.enabled && TRIGGER_TO_STAGE[r.trigger] === s.key).map(r => (
                  <button
                    key={r.key}
                    onClick={() => setConfiguring(r)}
                    style={{ fontSize: 10, padding: '2px 8px', borderRadius: 8, border: '1px dashed var(--acc)', color: 'var(--acc)', background: 'transparent' }}
                  >
                    {r.icon} {r.name}
                  </button>
                ))}
              </div>
              {i < arr.length - 1 && <span style={{ color: 'var(--line2)', marginTop: 6 }}>→</span>}
            </div>
          ))}
        </div>
        <div style={{ marginTop: 14, fontSize: 10.5, color: 'var(--mut)' }}>
          ⚠ blocked shows inside In progress · done gate: review config on each ticket · all criteria met
        </div>
      </Card>

      {/* Board stages */}
      <Card style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 10 }}><SectionLabel>Board stages</SectionLabel></div>
        {stages.map(s => (
          <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
            <span style={{ color: 'var(--mut)' }}>⠿</span>
            <span style={{ fontSize: 13, color: 'var(--ink)', flex: 1 }}>{s.label}</span>
            <span style={{ fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>{s.statuses.join(', ')}</span>
            {s.required && <Chip soft color="var(--mut)">required</Chip>}
            <Toggle checked={s.enabled} onChange={checked => handleToggleStage(s.key, checked)} disabled={s.required} />
          </div>
        ))}
      </Card>

      {/* Default agents */}
      <Card style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 10 }}><SectionLabel>Default agents</SectionLabel></div>
        {roles.map(r => (
          <div key={r.key} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
            <div style={{ width: 30, height: 30, borderRadius: 8, background: 'var(--card2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, flexShrink: 0 }}>{r.icon}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{r.name}</div>
              <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>{r.description}</div>
              <div style={{ fontSize: 10.5, color: 'var(--acc)', marginTop: 2 }}>fires {TRIGGER_LABELS[r.trigger] || r.trigger}</div>
            </div>
            <button onClick={() => setConfiguring(r)} style={{ fontSize: 12, fontWeight: 600, color: 'var(--acc)', padding: '4px 10px' }}>Configure</button>
            <Toggle checked={r.enabled} onChange={checked => updateRole(r.key, { enabled: checked }).then(load)} />
          </div>
        ))}
      </Card>

      {/* Start a pipeline */}
      <Card>
        <div style={{ marginBottom: 10 }}><SectionLabel>Start a pipeline</SectionLabel></div>
        {PIPELINE_TEMPLATES.map(t => (
          <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--ink)' }}>{t.name}</div>
              <div style={{ fontSize: 11, color: 'var(--mut)' }}>{t.description}</div>
            </div>
            <button onClick={() => navigate('/tasks')} style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--acc)', padding: '4px 10px' }}>
              Use on a task…
            </button>
          </div>
        ))}
      </Card>

      {configuring && (
        <RoleConfigDialog
          role={configuring}
          onClose={() => setConfiguring(null)}
          onSaved={() => { setConfiguring(null); load() }}
        />
      )}
    </DeskLayout>
  )
}

function RoleConfigDialog({ role, onClose, onSaved }: { role: RoleInfo; onClose: () => void; onSaved: () => void }) {
  const [model, setModel] = useState(role.model)
  const [provider, setProvider] = useState(role.provider || '')
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [trigger, setTrigger] = useState(role.trigger)
  const [prompt, setPrompt] = useState(role.prompt)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetchSettings().then(s => setProviders(s.providers)).catch(() => {})
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateRole(role.key, { model, provider, trigger, prompt })
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onClose={onClose} width={460}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>{role.icon} Configure {role.name}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Provider">
          <select aria-label="Provider" value={provider} onChange={e => setProvider(e.target.value)} style={inputStyle}>
            <option value="">(use workspace/global default)</option>
            {providers.map(p => <option key={p.name} value={p.name}>{p.name} ({p.model})</option>)}
          </select>
        </Field>
        <Field label="Model">
          <input aria-label="Model" value={model} onChange={e => setModel(e.target.value)} placeholder="(use provider's default)" style={inputStyle} />
        </Field>
        <Field label="Trigger">
          <select aria-label="Trigger" value={trigger} onChange={e => setTrigger(e.target.value)} style={inputStyle}>
            {Object.entries(TRIGGER_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="System prompt">
          <textarea aria-label="System prompt" value={prompt} onChange={e => setPrompt(e.target.value)} rows={5} style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
        </Field>
        <Field label="Allowed tools">
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {role.tools.map(t => <Chip key={t} mono>{t}</Chip>)}
          </div>
        </Field>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button onClick={onClose} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
          <button onClick={handleSave} disabled={saving} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)' }}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}

export default Workflows
