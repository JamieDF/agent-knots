/** Board/List stage config — EXPLICITLY STUBBED for Phase 1.
 *
 * The real Workflows screen (Phase 4) will let users configure/reorder
 * stages and persist them via a backend store. Until then this is a
 * hardcoded client-side mirror of the design handoff's default stage
 * set (README §3: "default Draft / Open / In progress / Review / Done;
 * Abandoned exists but is off by default").
 *
 * Status→stage mapping: open+planned → Open, in_progress+blocked → In
 * progress — blocked/planned surface as card badges, not their own
 * columns (see README §3).
 */

export interface Stage {
  key: string
  label: string
  statuses: string[]
  enabled: boolean
}

export const STAGES: Stage[] = [
  { key: 'draft', label: 'Draft', statuses: ['draft'], enabled: true },
  { key: 'open', label: 'Open', statuses: ['open', 'planned'], enabled: true },
  { key: 'in_progress', label: 'In progress', statuses: ['in_progress', 'blocked'], enabled: true },
  { key: 'review', label: 'Review', statuses: ['review'], enabled: true },
  { key: 'done', label: 'Done', statuses: ['done'], enabled: true },
  { key: 'abandoned', label: 'Abandoned', statuses: ['abandoned'], enabled: false },
]

export function enabledStages(): Stage[] {
  return STAGES.filter(s => s.enabled)
}

export function stageForStatus(status: string): Stage | undefined {
  return STAGES.find(s => s.statuses.includes(status))
}
