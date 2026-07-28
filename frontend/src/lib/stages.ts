import { useEffect, useState } from 'react'
import { fetchStages } from './api'

/** Board/List stage config — backed by the Workflows screen's real
 * config store. DEFAULT_STAGES is only the initial-paint fallback before
 * the first fetch resolves, mirroring the backend's own defaults
 * (agent_knots.workflows.models.DEFAULT_STAGES) so there's no visible
 * flash of different content.
 *
 * Status→stage mapping: open+planned → Open, in_progress+blocked → In
 * progress — blocked/planned surface as card badges, not their own
 * columns.
 */

export interface Stage {
  key: string
  label: string
  statuses: string[]
  enabled: boolean
  required: boolean
}

export const DEFAULT_STAGES: Stage[] = [
  { key: 'draft', label: 'Draft', statuses: ['draft'], enabled: true, required: true },
  { key: 'open', label: 'Open', statuses: ['open', 'planned'], enabled: true, required: false },
  { key: 'in_progress', label: 'In progress', statuses: ['in_progress', 'blocked'], enabled: true, required: false },
  { key: 'review', label: 'Review', statuses: ['review'], enabled: true, required: false },
  { key: 'done', label: 'Done', statuses: ['done'], enabled: true, required: true },
  { key: 'abandoned', label: 'Abandoned', statuses: ['abandoned'], enabled: false, required: false },
]

/** Fetches the real stage config on mount; components share the same
 * shape whether they got the fallback or the real data. */
export function useStages(): Stage[] {
  const [stages, setStages] = useState<Stage[]>(DEFAULT_STAGES)
  useEffect(() => {
    fetchStages().then(d => setStages(d.stages)).catch(() => {})
  }, [])
  return stages
}

export function enabledStages(stages: Stage[]): Stage[] {
  return stages.filter(s => s.enabled)
}

export function stageForStatus(stages: Stage[], status: string): Stage | undefined {
  return stages.find(s => s.statuses.includes(status))
}
