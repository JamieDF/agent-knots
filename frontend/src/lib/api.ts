/** API client for the agentjam backend. */

export interface AgentInfo {
  id: string
  mode: string
  task_id: string | null
  project_id: string | null
  tokens_used: number
  cost_usd: number
  running: boolean
}

export interface AgentsResponse {
  agents: AgentInfo[]
}

export interface SettingsResponse {
  configured: boolean
  agent: {
    default_model: string
    api_key: string     // masked
    base_url: string
    default_mode: string
  }
}

export async function fetchAgents(): Promise<AgentsResponse> {
  const res = await fetch('/api/agents')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function fetchSettings(): Promise<SettingsResponse> {
  const res = await fetch('/api/settings')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function saveSettings(settings: {
  default_model: string
  api_key: string
  base_url: string
  default_mode: string
}): Promise<{ status: string; configured: boolean }> {
  const res = await fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function createSession(body: {
  prompt: string
  mode?: string
}): Promise<{ id: string; mode: string; running: boolean }> {
  const res = await fetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function assumeAgent(id: string): Promise<void> {
  await fetch(`/api/agent/${id}/assume`, { method: 'POST' })
}

export async function relinquishAgent(id: string): Promise<void> {
  await fetch(`/api/agent/${id}/relinquish`, { method: 'POST' })
}

export async function sendMessage(id: string, message: string): Promise<void> {
  const body = new URLSearchParams({ message })
  await fetch(`/api/agent/${id}/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
}
