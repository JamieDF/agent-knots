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

export async function fetchAgents(): Promise<AgentsResponse> {
  const res = await fetch('/api/agents')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
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
