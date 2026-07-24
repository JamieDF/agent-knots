import { useCallback, useEffect, useState } from 'react'
import { Card, Chip, Field, SectionLabel, Toggle, inputStyle } from '../../components/primitives'
import { createTool, deleteTool, fetchTools, toggleTool, type ToolInfo } from '../../lib/api'
import { accentTextBtnStyle, deleteBtnStyle, FormDialog } from './shared'

export function ToolsCard() {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [showAdd, setShowAdd] = useState(false)

  const load = useCallback(() => { fetchTools().then(d => setTools(d.tools)).catch(() => {}) }, [])
  useEffect(() => { load() }, [load])

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>Tools</SectionLabel>
        <button onClick={() => setShowAdd(true)} style={accentTextBtnStyle({ marginLeft: 'auto' })}>+ Custom tool</button>
      </div>
      {tools.map(t => (
        <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--ink)', minWidth: 120 }}>{t.name}</span>
          <span style={{ fontSize: 11.5, color: 'var(--mut)', flex: 1 }}>{t.description}</span>
          <Chip soft color={t.builtin ? 'var(--mut)' : 'var(--acc)'}>{t.builtin ? 'BUILT-IN' : 'CUSTOM'}</Chip>
          <Toggle checked={t.enabled} onChange={async () => { await toggleTool(t.name); load() }} />
          {!t.builtin && <button onClick={async () => { await deleteTool(t.name); load() }} style={deleteBtnStyle}>✕</button>}
        </div>
      ))}
      <CustomToolDialog open={showAdd} onClose={() => setShowAdd(false)} onSaved={() => { setShowAdd(false); load() }} />
    </Card>
  )
}

function CustomToolDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [command, setCommand] = useState('')
  const [params, setParams] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const reset = () => { setName(''); setDescription(''); setCommand(''); setParams(''); setError('') }
  const close = () => { reset(); onClose() }

  const parseParams = () => params.split(',').map(s => s.trim()).filter(Boolean).map(entry => {
    const [pname, ptype] = entry.split(':').map(s => s.trim())
    return { name: pname, type: ptype || 'string', description: '' }
  })

  const handleSave = async () => {
    if (!name.trim() || !command.trim()) return
    setSaving(true); setError('')
    try {
      await createTool({ name: name.trim(), description, command: command.trim(), parameters: parseParams() })
      reset()
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create tool')
    } finally {
      setSaving(false)
    }
  }

  return (
    <FormDialog
      open={open} onClose={close} title="+ Custom tool" width={460}
      onSave={handleSave} saveDisabled={!name.trim() || !command.trim()} saving={saving} error={error}
    >
      <Field label="Name"><input aria-label="Tool name" value={name} onChange={e => setName(e.target.value)} placeholder="run_tests" style={inputStyle} /></Field>
      <Field label="Description"><input aria-label="Tool description" value={description} onChange={e => setDescription(e.target.value)} placeholder="optional" style={inputStyle} /></Field>
      <Field label="Shell command"><input aria-label="Shell command" value={command} onChange={e => setCommand(e.target.value)} placeholder="pytest {path} -v" style={{ ...inputStyle, fontFamily: 'var(--font-mono)' }} /></Field>
      <Field label="Params"><input aria-label="Params" value={params} onChange={e => setParams(e.target.value)} placeholder="path:string, verbose:boolean" style={inputStyle} /></Field>
    </FormDialog>
  )
}
