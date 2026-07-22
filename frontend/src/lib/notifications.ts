import { useEffect, useState } from 'react'
import { fetchTasks, type TaskSummary } from './api'

export interface NotificationItem {
  id: string
  kind: 'blocker' | 'done'
  title: string
  taskId: string
  time: number
}

/** Derives notifications from the tasks list rather than a live SSE
 * subscription — a global bell watching every active session's own
 * event stream simultaneously is a much bigger lift than polling the
 * same tasks list the Dashboard already polls, for the same practical
 * result (blocked tasks page you regardless; done tasks you'll see on
 * your next task-list visit either way). The badge count is
 * specifically pending blockers, per the design's own copy — "tests"
 * notifications are left out entirely since nothing in this backend
 * produces test-run data to derive them from. */
export function useNotifications() {
  const [tasks, setTasks] = useState<TaskSummary[]>([])

  useEffect(() => {
    let mounted = true
    const poll = async () => {
      try {
        const d = await fetchTasks({ limit: 300 })
        if (mounted) setTasks(d.tasks)
      } catch { /* ignore */ }
    }
    poll()
    const interval = setInterval(poll, 5000)
    return () => { mounted = false; clearInterval(interval) }
  }, [])

  const now = Date.now() / 1000
  const blockers: NotificationItem[] = tasks
    .filter(t => t.status === 'blocked')
    .map(t => ({ id: `blocker:${t.id}`, kind: 'blocker' as const, title: t.title, taskId: t.id, time: t.updated_at }))
  const recentlyDone: NotificationItem[] = tasks
    .filter(t => t.status === 'done' && now - t.updated_at < 86400)
    .map(t => ({ id: `done:${t.id}`, kind: 'done' as const, title: t.title, taskId: t.id, time: t.updated_at }))

  const items = [...blockers, ...recentlyDone].sort((a, b) => b.time - a.time)
  return { items, blockerCount: blockers.length }
}
