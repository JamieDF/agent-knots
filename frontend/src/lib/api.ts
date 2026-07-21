/** API client for the agent-knots backend. */

// ── types ───────────────────────────────────────────────────────────────────

export interface AgentInfo {
  id: string; mode: string; task_id: string | null; project_id: string | null
  tokens_used: number; cost_usd: number; running: boolean
}

export interface SettingsResponse {
  configured: boolean
  agent: { default_model: string; api_key: string; base_url: string; default_mode: string }
}

export interface TaskSummary {
  id: string; title: string; status: string; priority: string
  tags: string[]; project: string; assigned_to: string
  created_at: number; updated_at: number
  progress_count: number; steps_count: number; criteria_count: number
}

export interface TaskDetail {
  id: string; title: string; description: string
  status: string; priority: string; tags: string[]; project: string
  assigned_to: string; created_at: number; updated_at: number; created_by: string
  acceptance_criteria: string[]; out_of_scope: string[]; dependencies: string[]
  required_credentials: string[]
  steps: { id: string; title: string; status: string; notes: string; sub_steps: any[] }[]
  progress: {
    timestamp: number; status: string; entry: string
    actions_taken: string[]; resolution: string; next_step: string; caller: string
    blocker: { description: string; question: string; options: string[]; awaiting: string } | null
  }[]
}

// ── agents ──────────────────────────────────────────────────────────────────

export async function fetchAgents(): Promise<{ agents: AgentInfo[] }> {
  const res = await fetch('/api/agents'); if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json()
}
export async function assumeAgent(id: string): Promise<void> { await fetch(`/api/agent/${id}/assume`, { method: 'POST' }) }
export async function relinquishAgent(id: string): Promise<void> { await fetch(`/api/agent/${id}/relinquish`, { method: 'POST' }) }
export async function sendMessage(id: string, message: string): Promise<void> {
  await fetch(`/api/agent/${id}/send`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ message }) })
}
export async function fetchSettings(): Promise<SettingsResponse> {
  const res = await fetch('/api/settings'); if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json()
}
export async function saveSettings(s: { default_model: string; api_key: string; base_url: string; default_mode: string }) {
  const res = await fetch('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(s) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json()
}
export async function createSession(body: { prompt: string; mode?: string; project_id?: string; task_id?: string }) {
  const res = await fetch('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) { const err = await res.json(); throw new Error(err.detail || `HTTP ${res.status}`) }
  return res.json()
}

// ── tasks ───────────────────────────────────────────────────────────────────

export async function fetchTasks(params?: { status?: string; project?: string; limit?: number }): Promise<{ tasks: TaskSummary[] }> {
  const qs = new URLSearchParams()
  if (params?.status) qs.set('status', params.status)
  if (params?.project) qs.set('project', params.project)
  if (params?.limit) qs.set('limit', String(params.limit))
  const res = await fetch('/api/tasks' + (qs.toString() ? '?' + qs.toString() : ''))
  if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json()
}

export async function fetchTask(id: string): Promise<TaskDetail> {
  const res = await fetch(`/api/tasks/${id}`); if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json()
}

export async function createTask(data: {
  title: string; description?: string; priority?: string; tags?: string[]; acceptance_criteria?: string[]
}): Promise<TaskDetail> {
  const res = await fetch('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json()
}

export async function updateTask(id: string, data: { status?: string; priority?: string; title?: string; description?: string; assign?: string }): Promise<TaskDetail> {
  const res = await fetch(`/api/tasks/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json()
}

export async function deleteTask(id: string): Promise<void> {
  await fetch(`/api/tasks/${id}`, { method: 'DELETE' })
}

// ── tools ───────────────────────────────────────────────────────────────────

export interface ToolInfo {
  name: string; description: string; builtin: boolean; enabled: boolean; created_at: number
}

export async function fetchTools(): Promise<{ tools: ToolInfo[] }> {
  const res = await fetch('/api/tools'); if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json()
}

export async function createTool(data: { name: string; description?: string; command: string; parameters?: {name:string,type:string,description:string}[] }) {
  const res = await fetch('/api/tools', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) { const err = await res.json(); throw new Error(err.detail) }; return res.json()
}

export async function updateTool(name: string, data: { description?: string; command?: string; parameters?: any[] }) {
  const res = await fetch(`/api/tools/${name}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json()
}

export async function deleteTool(name: string): Promise<void> {
  const res = await fetch(`/api/tools/${name}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}

export async function toggleTool(name: string): Promise<{ enabled: boolean }> {
  const res = await fetch(`/api/tools/${name}/toggle`, { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json()
}

// ── workspaces ──────────────────────────────────────────────────────────────

export interface Workspace {
  id: string; name: string; description: string; repository: string; tags: string[]
  created_at: number
}

export async function fetchWorkspaces(): Promise<{ workspaces: Workspace[] }> {
  const res = await fetch('/api/workspaces'); if (!res.ok) throw new Error(''); return res.json()
}

export async function createWorkspace(data: { id: string; name: string; description?: string; repository?: string; tags?: string[] }) {
  const res = await fetch('/api/workspaces', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) { const err = await res.json(); throw new Error(err.detail) }; return res.json()
}

export async function updateWorkspace(id: string, data: { name?: string; description?: string; repository?: string; tags?: string[] }) {
  const res = await fetch(`/api/workspaces/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw new Error(''); return res.json()
}

export async function deleteWorkspace(id: string): Promise<void> {
  const res = await fetch(`/api/workspaces/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('')
}
export async function deleteAgent(id: string): Promise<void> {
  await fetch(`/api/agent/${id}`, { method: 'DELETE' })
}
