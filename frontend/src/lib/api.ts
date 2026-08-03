/** API client for the agent-knots backend. */

// ── fetch helpers ─────────────────────────────────────────────────────────────
// Every route below used to hand-roll its own error handling, and had
// drifted into three inconsistent variants: throw new Error(`HTTP
// ${status}`), throw new Error('') (no message at all — the UI's error
// boxes rendered blank), and `const err = await res.json(); throw new
// Error(err.detail)` (which itself throws a confusing JSON-parse error
// if the error body isn't valid JSON, instead of the real failure). A
// few mutating calls (setAutonomous, sendMessage, deleteAgent, etc.)
// didn't check res.ok at all, silently succeeding from the caller's
// perspective on a failed request. apiFetch() unifies all of that:
// always throws with the backend's `detail` message when present,
// falls back to a plain HTTP status, and never masks a real failure
// behind a secondary JSON-parse error.

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) }
}

// ── types ───────────────────────────────────────────────────────────────────

export interface AgentInfo {
  id: string; name: string; mode: string; task_id: string | null; project_id: string | null
  tokens_used: number; cost_usd: number; running: boolean
  model: string; started_at: number
  pending_question: { question: string; options: string[] | null } | null
  branch: string | null; advisory: boolean; role: string
  last_activity: string
}

export interface ProviderInfo {
  name: string; model: string; base_url: string; key_set: boolean; is_default: boolean
}

export interface IntegrationsInfo {
  github_pr_on_review: boolean; phone_push: boolean
}

export interface SettingsResponse {
  configured: boolean
  agent: { default_model: string; api_key: string; base_url: string; default_mode: string }
  providers: ProviderInfo[]
  default_provider: string
  integrations: IntegrationsInfo
  wastebin: { retention_days: number }
}

export interface WastebinEntry {
  session_id: string; name: string; task_id: string | null; task_title: string; project_id: string | null
  branch: string | null; working_dir: string; is_auto_workdir: boolean
  role: string; advisory: boolean; model: string
  tokens_used: number; cost_usd: number; started_at: number; stopped_at: number
}

export interface TaskSummary {
  id: string; title: string; status: string; priority: string
  tags: string[]; project: string; assigned_to: string
  created_at: number; updated_at: number
  progress_count: number; steps_count: number; criteria_count: number
  blocked_by_deps: boolean
}

export interface TaskDetail {
  id: string; title: string; description: string
  status: string; priority: string; tags: string[]; project: string
  review_gate: string
  assigned_to: string; created_at: number; updated_at: number; created_by: string
  acceptance_criteria: string[]; criteria_met: string[]; out_of_scope: string[]; dependencies: string[]
  unmet_dependencies: { id: string; title: string }[]
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
  return apiFetch('/api/agents')
}
export async function fetchAgent(id: string): Promise<AgentInfo> {
  return apiFetch(`/api/agent/${id}`)
}
export async function setAutonomous(id: string, on: boolean): Promise<void> {
  await apiFetch(`/api/agent/${id}/autonomous`, jsonInit('POST', { on }))
}
export async function checkpointAgent(id: string, label: string): Promise<void> {
  await apiFetch(`/api/agent/${id}/checkpoint`, jsonInit('POST', { label }))
}
export async function revertAgent(id: string, label: string): Promise<void> {
  await apiFetch(`/api/agent/${id}/revert`, jsonInit('POST', { label }))
}
export async function interruptAgent(id: string): Promise<void> {
  await apiFetch(`/api/agent/${id}/interrupt`, { method: 'POST' })
}
export async function fetchAgentFile(id: string, path: string): Promise<{ path: string; content: string; truncated: boolean }> {
  return apiFetch(`/api/agent/${id}/file?path=${encodeURIComponent(path)}`)
}
export async function sendMessage(id: string, message: string): Promise<void> {
  await apiFetch(`/api/agent/${id}/send`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ message }) })
}
export async function answerAgent(id: string, answer: string): Promise<void> {
  await apiFetch(`/api/agent/${id}/answer`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ answer }) })
}
export interface PendingQuestion {
  agent_id: string; agent_name: string; task_id: string | null; question: string; options: string[] | null
}
export async function fetchPendingQuestions(): Promise<{ questions: PendingQuestion[] }> {
  return apiFetch('/api/agents/pending-questions')
}
export async function fetchSettings(): Promise<SettingsResponse> {
  return apiFetch('/api/settings')
}
export async function saveSettings(s: { default_model: string; api_key: string; base_url: string; default_mode: string; wastebin_retention_days?: number }) {
  return apiFetch<any>('/api/settings', jsonInit('PUT', s))
}
export async function createSession(body: { prompt: string; mode?: string; project_id?: string; task_id?: string }) {
  return apiFetch<any>('/api/sessions', jsonInit('POST', body))
}

// ── tasks ───────────────────────────────────────────────────────────────────

export async function fetchTasks(params?: { status?: string; project?: string; limit?: number }): Promise<{ tasks: TaskSummary[] }> {
  const qs = new URLSearchParams()
  if (params?.status) qs.set('status', params.status)
  if (params?.project) qs.set('project', params.project)
  if (params?.limit) qs.set('limit', String(params.limit))
  return apiFetch('/api/tasks' + (qs.toString() ? '?' + qs.toString() : ''))
}

export async function fetchTask(id: string): Promise<TaskDetail> {
  return apiFetch(`/api/tasks/${id}`)
}

export async function fetchTaskAgents(id: string): Promise<{ agents: AgentInfo[] }> {
  return apiFetch(`/api/tasks/${id}/agents`)
}

export interface PastSession {
  id: string; name: string; role: string; advisory: boolean; model: string
  tokens_used: number; cost_usd: number; started_at: number; stopped_at: number
}

export async function fetchTaskHistory(id: string): Promise<{ sessions: PastSession[] }> {
  return apiFetch(`/api/tasks/${id}/history`)
}

export async function createTask(data: {
  title: string; description?: string; priority?: string; tags?: string[]
  acceptance_criteria?: string[]; review_gate?: string; project?: string
  dependencies?: string[]
}): Promise<TaskDetail> {
  return apiFetch('/api/tasks', jsonInit('POST', data))
}

export async function updateTask(id: string, data: {
  status?: string; priority?: string; title?: string; description?: string; assign?: string
  tags?: string[]; acceptance_criteria?: string[]; steps?: string[]; review_gate?: string
  dependencies?: string[]
}): Promise<TaskDetail> {
  return apiFetch(`/api/tasks/${id}`, jsonInit('PATCH', data))
}

export async function toggleCriterion(id: string, criterion: string, met: boolean): Promise<TaskDetail> {
  return apiFetch(`/api/tasks/${id}/criteria/toggle`, jsonInit('POST', { criterion, met }))
}

export async function draftTask(title: string): Promise<{ description: string; acceptance_criteria: string[]; tags: string[]; steps: string[] }> {
  return apiFetch('/api/tasks/draft', jsonInit('POST', { title }))
}

export async function deleteTask(id: string): Promise<void> {
  await apiFetch(`/api/tasks/${id}`, { method: 'DELETE' })
}

// ── tools ───────────────────────────────────────────────────────────────────

export interface ToolInfo {
  name: string; description: string; builtin: boolean; enabled: boolean; created_at: number
}

export async function fetchTools(): Promise<{ tools: ToolInfo[] }> {
  return apiFetch('/api/tools')
}

export async function createTool(data: { name: string; description?: string; command: string; parameters?: {name:string,type:string,description:string}[] }) {
  return apiFetch<any>('/api/tools', jsonInit('POST', data))
}

export async function deleteTool(name: string): Promise<void> {
  await apiFetch(`/api/tools/${name}`, { method: 'DELETE' })
}

export async function toggleTool(name: string): Promise<{ enabled: boolean }> {
  return apiFetch(`/api/tools/${name}/toggle`, { method: 'POST' })
}

// ── workspaces ──────────────────────────────────────────────────────────────

export interface Workspace {
  id: string; name: string; description: string; repository: string; runtime: string; tags: string[]
  auto_assign: boolean; max_concurrent: number; archived: boolean
  created_at: number
}

export async function fetchWorkspaces(includeArchived = false): Promise<{ workspaces: Workspace[] }> {
  return apiFetch(`/api/workspaces${includeArchived ? '?include_archived=true' : ''}`)
}

export async function fetchWorkspace(id: string): Promise<Workspace> {
  return apiFetch(`/api/workspaces/${id}`)
}

export async function createWorkspace(data: { id?: string; name: string; description?: string; repository?: string; runtime?: string; tags?: string[]; auto_assign?: boolean; max_concurrent?: number }) {
  return apiFetch<any>('/api/workspaces', jsonInit('POST', data))
}

export async function updateWorkspace(id: string, data: { name?: string; description?: string; repository?: string; runtime?: string; tags?: string[]; auto_assign?: boolean; max_concurrent?: number; archived?: boolean }) {
  return apiFetch<any>(`/api/workspaces/${id}`, jsonInit('PATCH', data))
}

export async function deleteWorkspace(id: string): Promise<void> {
  await apiFetch(`/api/workspaces/${id}`, { method: 'DELETE' })
}
export async function deleteAgent(id: string): Promise<void> {
  await apiFetch(`/api/agent/${id}`, { method: 'DELETE' })
}

// ── workflows: stages + roles ────────────────────────────────────────────────

export interface StageInfo {
  key: string; label: string; statuses: string[]; enabled: boolean; required: boolean
}

export async function fetchStages(): Promise<{ stages: StageInfo[] }> {
  return apiFetch('/api/stages')
}

export async function toggleStage(key: string, enabled: boolean): Promise<{ stages: StageInfo[] }> {
  return apiFetch(`/api/stages/${key}/toggle`, jsonInit('POST', { enabled }))
}

export interface RoleInfo {
  key: string; name: string; icon: string; description: string
  model: string; trigger: string; prompt: string; tools: string[]; enabled: boolean
}

export async function fetchRoles(): Promise<{ roles: RoleInfo[] }> {
  return apiFetch('/api/roles')
}

export async function updateRole(key: string, data: { model?: string; trigger?: string; prompt?: string; enabled?: boolean }): Promise<RoleInfo> {
  return apiFetch(`/api/roles/${key}`, jsonInit('PATCH', data))
}

// ── review ───────────────────────────────────────────────────────────────────
// Task-keyed: one task in review, with its own file diffs and its own
// approve/reject flow. Reject is a real "send it back" action — it
// moves the task to in_progress and resumes its (usually still paused,
// not stopped — see task/lifecycle.py) session with the feedback.

export interface ReviewTask {
  id: string; title: string; project: string; project_name: string
  branch: string; session_id: string | null; session_name: string
}

export interface ReviewDiff {
  file: string; added: number; deleted: number
}

export async function fetchReviewTasks(): Promise<{ tasks: ReviewTask[] }> {
  return apiFetch('/api/review/tasks')
}

export async function fetchReviewDiffs(taskId: string): Promise<{ branch: string; diffs: ReviewDiff[] }> {
  return apiFetch(`/api/review/diffs?task_id=${encodeURIComponent(taskId)}`)
}

export async function fetchReviewDiffText(taskId: string, file: string): Promise<{ diff: string }> {
  return apiFetch(`/api/review/diff?task_id=${encodeURIComponent(taskId)}&file=${encodeURIComponent(file)}`)
}

export async function approveReview(
  taskId: string, file?: string,
): Promise<{ status: string; task_status?: string; done_error?: string }> {
  return apiFetch('/api/review/approve', jsonInit('POST', { task_id: taskId, file }))
}

export async function rejectReview(
  taskId: string, reason: string, approvedFiles: string[], file?: string,
): Promise<{ status: string; task_status: string; session_id: string }> {
  return apiFetch('/api/review/reject', jsonInit('POST', {
    task_id: taskId, file, reason, approved_files: approvedFiles,
  }))
}

// ── wastebin ────────────────────────────────────────────────────────────────

export async function fetchWastebin(): Promise<{ entries: WastebinEntry[] }> {
  return apiFetch('/api/wastebin')
}
export async function deleteWastebinEntry(sessionId: string): Promise<void> {
  await apiFetch(`/api/wastebin/${sessionId}`, { method: 'DELETE' })
}

// ── providers + integrations ─────────────────────────────────────────────────

export async function addProvider(data: { name: string; model?: string; api_key?: string; base_url?: string }): Promise<{ providers: ProviderInfo[] }> {
  return apiFetch('/api/settings/providers', jsonInit('POST', data))
}

export async function deleteProvider(name: string): Promise<{ providers: ProviderInfo[] }> {
  return apiFetch(`/api/settings/providers/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

export async function setDefaultProvider(name: string): Promise<void> {
  await apiFetch(`/api/settings/providers/${encodeURIComponent(name)}/default`, { method: 'POST' })
}

export async function saveIntegrations(data: { github_pr_on_review?: boolean; phone_push?: boolean }): Promise<void> {
  await apiFetch('/api/integrations', jsonInit('PUT', data))
}

// ── usage ────────────────────────────────────────────────────────────────────

export interface UsageSummary {
  today: { tokens: number; cost_usd: number }
  month: { tokens: number; cost_usd: number }
  by_provider: { provider: string; tokens: number; cost_usd: number }[]
  top_tasks: { task_id: string; tokens: number }[]
}

export async function fetchUsage(): Promise<UsageSummary> {
  return apiFetch('/api/usage')
}

// ── policies ─────────────────────────────────────────────────────────────────

export interface PolicyInfo {
  key: string; label: string; description: string; enabled: boolean; value: string; enforced: boolean
}

export async function fetchPolicies(): Promise<{ policies: PolicyInfo[] }> {
  return apiFetch('/api/policies')
}

export async function updatePolicy(key: string, data: { enabled?: boolean; value?: string }): Promise<PolicyInfo> {
  return apiFetch(`/api/policies/${key}`, jsonInit('PATCH', data))
}

// ── MCP servers ──────────────────────────────────────────────────────────────

export interface McpServerInfo {
  name: string; url: string; enabled: boolean; tool_count: number; created_at: number
}

export async function fetchMcpServers(): Promise<{ servers: McpServerInfo[] }> {
  return apiFetch('/api/mcp')
}

export async function fetchMcpServer(name: string): Promise<McpServerInfo> {
  return apiFetch(`/api/mcp/${encodeURIComponent(name)}`)
}

export async function addMcpServer(data: { name: string; url?: string }): Promise<{ servers: McpServerInfo[] }> {
  return apiFetch('/api/mcp', jsonInit('POST', data))
}

export async function toggleMcpServer(name: string, enabled: boolean): Promise<McpServerInfo> {
  return apiFetch(`/api/mcp/${encodeURIComponent(name)}/toggle`, jsonInit('POST', { enabled }))
}

export async function deleteMcpServer(name: string): Promise<void> {
  await apiFetch(`/api/mcp/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

// ── vault ────────────────────────────────────────────────────────────────────

export interface CredentialInfo {
  id: string; description: string; tags: string[]
  created_at: number; last_used: number; uses_total: number
  templates: { name: string; description: string; env: Record<string, string>; file_path: string | null; stdin: boolean; command_wrapper: string | null }[]
}

export interface AuditEntryInfo {
  timestamp: number; credential: string; template: string; command: string
  caller: string; success: boolean; error: string
}

export async function fetchVaultStatus(): Promise<{ lock_state: 'locked' | 'unlocked' | 'uninitialized' }> {
  return apiFetch('/api/vault/status')
}

export async function unlockVault(passphrase: string): Promise<{ lock_state: string }> {
  return apiFetch('/api/vault/unlock', jsonInit('POST', { passphrase }))
}

export async function lockVault(): Promise<void> {
  await apiFetch('/api/vault/lock', { method: 'POST' })
}

export async function fetchCredentials(): Promise<{ credentials: CredentialInfo[] }> {
  return apiFetch('/api/vault/credentials')
}

export async function addCredential(data: { id: string; description?: string; tags?: string[]; value: string }): Promise<void> {
  await apiFetch('/api/vault/credentials', jsonInit('POST', data))
}

export async function deleteCredential(id: string): Promise<void> {
  await apiFetch(`/api/vault/credentials/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export async function fetchAuditLog(limit = 50): Promise<{ entries: AuditEntryInfo[] }> {
  return apiFetch(`/api/vault/audit?limit=${limit}`)
}

// ── filesystem browse (workspace folder picker) ──────────────────────────────

export interface FsEntry {
  name: string; path: string; is_git: boolean
}

export async function fetchFsBrowse(path?: string): Promise<{ path: string; parent: string | null; entries: FsEntry[] }> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : ''
  return apiFetch(`/api/fs/browse${qs}`)
}

export async function fetchGitInfo(path: string): Promise<{ is_git: boolean; github_url: string | null }> {
  return apiFetch(`/api/fs/git-info?path=${encodeURIComponent(path)}`)
}
