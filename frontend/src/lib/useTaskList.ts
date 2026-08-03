import { useCallback, useEffect, useState } from 'react'
import { fetchTasks, type TaskSummary } from './api'
import { useStages, type Stage } from './stages'
import { useWorkspaceScope } from './workspaceContext'

const PRIORITY_ORDER: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 }

/** Shared task-fetching logic for the Board and List tabs of the Tasks
 * screen — both poll the same workspace-scoped, priority-sorted task
 * list every 5s and need to refetch immediately when a task is created
 * elsewhere (the Tasks screen header's own create dialog signals this
 * via reloadSignal, rather than waiting for the next poll tick), plus
 * the enabled stage config to group/filter by. */
export function useTaskList(reloadSignal?: number) {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  // Only true until the very first fetch settles — background polls
  // refreshing an already-loaded list shouldn't flip this back on and
  // flash a spinner over content that's already there.
  const [loading, setLoading] = useState(true)
  const { workspace } = useWorkspaceScope()
  const allStages: Stage[] = useStages()

  const load = useCallback(async () => {
    try {
      const data = await fetchTasks({ limit: 200, project: workspace || undefined })
      setTasks(data.tasks.sort((a, b) => (PRIORITY_ORDER[a.priority] ?? 2) - (PRIORITY_ORDER[b.priority] ?? 2)))
    } catch { /* ignore */ } finally {
      setLoading(false)
    }
  }, [workspace])

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [load])

  useEffect(() => { if (reloadSignal !== undefined) load() }, [reloadSignal]) // eslint-disable-line react-hooks/exhaustive-deps

  return { tasks, setTasks, load, loading, workspace, allStages }
}
