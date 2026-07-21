import { useEffect, useState } from 'react'
import { createTask, updateTask, draftTask, type TaskDetail } from '../lib/api'
import { Dialog, Chip } from './primitives'

interface Props {
  open: boolean
  onClose: () => void
  onSaved: () => void
  task?: TaskDetail | null
  initialStatus?: string
}

const STATUSES = ['draft', 'open', 'planned', 'in_progress', 'blocked', 'review', 'done', 'abandoned']
const PRIORITIES = ['low', 'medium', 'high', 'urgent']
const REVIEW_GATES = [
  { value: 'auto', label: 'Auto-review on completion' },
  { value: 'manual', label: 'Ask me' },
  { value: 'none', label: 'No review gate' },
]

/** Unified task create/edit dialog, replacing the old CreateTaskDialog.tsx
 * (3 fields only) and TaskDetail.tsx's separate edit modal. Per
 * design_handoff_atelier_cockpit/README.md §11: chip tags, criteria/steps
 * row-list editors, review-gate select, "✨ Draft with agent". Editing
 * preserves criteria_met/step status for unchanged items — enforced
 * server-side (PATCH matches by text), this dialog just sends the lists. */
function TaskDialog({ open, onClose, onSaved, task, initialStatus }: Props) {
  const isEdit = !!task

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState('medium')
  const [status, setStatus] = useState(initialStatus || 'open')
  const [reviewGate, setReviewGate] = useState('manual')
  const [tags, setTags] = useState<string[]>([])
  const [tagDraft, setTagDraft] = useState('')
  const [criteria, setCriteria] = useState<string[]>([])
  const [criterionDraft, setCriterionDraft] = useState('')
  const [steps, setSteps] = useState<string[]>([])
  const [stepDraft, setStepDraft] = useState('')
  const [drafting, setDrafting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    if (task) {
      setTitle(task.title)
      setDescription(task.description)
      setPriority(task.priority)
      setStatus(task.status)
      setReviewGate(task.review_gate)
      setTags(task.tags)
      setCriteria(task.acceptance_criteria)
      setSteps(task.steps.map(s => s.title))
    } else {
      setTitle(''); setDescription(''); setPriority('medium')
      setStatus(initialStatus || 'open'); setReviewGate('manual')
      setTags([]); setCriteria([]); setSteps([])
    }
    setError('')
  }, [open, task, initialStatus])

  const addTag = () => {
    const t = tagDraft.trim().replace(/,$/, '')
    if (t && !tags.includes(t)) setTags([...tags, t])
    setTagDraft('')
  }
  const onTagKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTag() }
    else if (e.key === 'Backspace' && !tagDraft && tags.length > 0) setTags(tags.slice(0, -1))
  }

  const addCriterion = () => {
    const c = criterionDraft.trim()
    if (c) setCriteria([...criteria, c])
    setCriterionDraft('')
  }
  const addStep = () => {
    const s = stepDraft.trim()
    if (s) setSteps([...steps, s])
    setStepDraft('')
  }

  const handleDraft = async () => {
    if (!title.trim()) return
    setDrafting(true); setError('')
    try {
      const d = await draftTask(title.trim())
      if (!description) setDescription(d.description)
      if (criteria.length === 0) setCriteria(d.acceptance_criteria)
      if (tags.length === 0) setTags(d.tags)
      if (steps.length === 0) setSteps(d.steps)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Draft failed')
    } finally {
      setDrafting(false)
    }
  }

  const handleSave = async () => {
    if (!title.trim()) return
    setSaving(true); setError('')
    try {
      if (isEdit && task) {
        await updateTask(task.id, {
          title: title.trim(), description, priority, status,
          review_gate: reviewGate, tags, acceptance_criteria: criteria, steps,
        })
      } else {
        await createTask({
          title: title.trim(), description, priority, review_gate: reviewGate,
          tags, acceptance_criteria: criteria,
        })
      }
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} width={560}>
      <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>{isEdit ? 'Edit task' : 'New task'}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 14 }}>
        <Field label="Title">
          <div style={{ display: 'flex', gap: 8 }}>
            <input autoFocus value={title} onChange={e => setTitle(e.target.value)} placeholder="What needs to be done?" style={inputStyle} />
            <button
              onClick={handleDraft}
              disabled={!title.trim() || drafting}
              style={{
                whiteSpace: 'nowrap', padding: '0 12px', borderRadius: 8, fontSize: 12, fontWeight: 600,
                background: 'var(--acc-soft)', color: 'var(--acc)',
                opacity: !title.trim() || drafting ? 0.5 : 1,
                cursor: !title.trim() || drafting ? 'not-allowed' : 'pointer',
              }}
            >
              {drafting ? 'Drafting…' : '✨ Draft with agent'}
            </button>
          </div>
        </Field>

        <Field label="Description">
          <textarea value={description} onChange={e => setDescription(e.target.value)} rows={3} style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
        </Field>

        <div style={{ display: 'grid', gridTemplateColumns: isEdit ? '1fr 1fr' : '1fr', gap: 10 }}>
          <Field label="Priority">
            <select aria-label="Priority" value={priority} onChange={e => setPriority(e.target.value)} style={inputStyle}>
              {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
          {isEdit && (
            <Field label="Status">
              <select aria-label="Status" value={status} onChange={e => setStatus(e.target.value)} style={inputStyle}>
                {STATUSES.map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
              </select>
            </Field>
          )}
        </div>

        <Field label="Review gate">
          <select aria-label="Review gate" value={reviewGate} onChange={e => setReviewGate(e.target.value)} style={inputStyle}>
            {REVIEW_GATES.map(g => <option key={g.value} value={g.value}>{g.label}</option>)}
          </select>
        </Field>

        <Field label="Tags">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '6px 8px', border: '1px solid var(--line2)', borderRadius: 8, background: 'var(--card2)' }}>
            {tags.map(t => (
              <Chip key={t} onClick={() => setTags(tags.filter(x => x !== t))}>{t} ×</Chip>
            ))}
            <input
              value={tagDraft}
              onChange={e => setTagDraft(e.target.value)}
              onKeyDown={onTagKey}
              placeholder={tags.length === 0 ? 'Enter or comma to add' : ''}
              style={{ border: 0, background: 'transparent', outline: 'none', flex: 1, minWidth: 80, fontSize: 13, color: 'var(--ink)' }}
            />
          </div>
        </Field>

        <Field label="Acceptance criteria" hint="Gates done — every criterion must be marked met before a task can complete.">
          <RowList
            items={criteria}
            prefix="○"
            draft={criterionDraft}
            onDraftChange={setCriterionDraft}
            onAdd={addCriterion}
            onRemove={i => setCriteria(criteria.filter((_, idx) => idx !== i))}
            placeholder="Add criterion…"
          />
        </Field>

        <Field label="Steps">
          <RowList
            items={steps}
            prefix={(i) => NUMERALS[i] ?? String(i + 1)}
            draft={stepDraft}
            onDraftChange={setStepDraft}
            onAdd={addStep}
            onRemove={i => setSteps(steps.filter((_, idx) => idx !== i))}
            placeholder="Add step…"
          />
        </Field>

        {error && <div style={{ color: 'var(--err)', fontSize: 13 }}>{error}</div>}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--mut)', fontFamily: 'var(--font-mono)' }}>Esc to cancel</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={onClose} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink2)', background: 'var(--card2)' }}>Cancel</button>
            <button
              onClick={handleSave}
              disabled={saving || !title.trim()}
              style={{
                padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600,
                background: title.trim() ? 'var(--acc)' : 'var(--card2)',
                color: title.trim() ? 'var(--acc-ink)' : 'var(--mut)',
                cursor: saving || !title.trim() ? 'not-allowed' : 'pointer',
              }}
            >
              {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create task'}
            </button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}

const NUMERALS = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <label style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--mut)' }}>{label}</label>
      {children}
      {hint && <span style={{ fontSize: 11, color: 'var(--mut)' }}>{hint}</span>}
    </div>
  )
}

function RowList({ items, prefix, draft, onDraftChange, onAdd, onRemove, placeholder }: {
  items: string[]
  prefix: string | ((i: number) => string)
  draft: string
  onDraftChange: (v: string) => void
  onAdd: () => void
  onRemove: (i: number) => void
  placeholder: string
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {items.map((item, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
          <span style={{ color: 'var(--mut)', width: 16, flexShrink: 0 }}>{typeof prefix === 'function' ? prefix(i) : prefix}</span>
          <span style={{ flex: 1, color: 'var(--ink2)' }}>{item}</span>
          <button onClick={() => onRemove(i)} style={{ color: 'var(--mut)', fontSize: 13, padding: '0 4px' }}>×</button>
        </div>
      ))}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span style={{ color: 'var(--mut)', width: 16, flexShrink: 0 }}>{typeof prefix === 'function' ? prefix(items.length) : prefix}</span>
        <input
          value={draft}
          onChange={e => onDraftChange(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); onAdd() } }}
          placeholder={placeholder}
          style={{ flex: 1, border: '1px solid var(--line2)', borderRadius: 6, padding: '5px 8px', fontSize: 13, background: 'var(--card2)', color: 'var(--ink)', outline: 'none' }}
        />
        <button onClick={onAdd} style={{ fontSize: 12, color: 'var(--acc)', fontWeight: 600, padding: '0 6px' }}>+ Add</button>
      </div>
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line2)',
  background: 'var(--card2)', color: 'var(--ink)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
}

export default TaskDialog
