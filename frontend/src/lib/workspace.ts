/** Workspace context — persisted to localStorage for the active workspace. */

const KEY = 'agentjam-active-workspace'

export function getActiveWorkspace(): string {
  return localStorage.getItem(KEY) || ''
}

export function setActiveWorkspace(id: string): void {
  localStorage.setItem(KEY, id)
}
