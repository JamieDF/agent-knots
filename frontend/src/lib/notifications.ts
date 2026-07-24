import { useEffect, useState } from 'react'
import { fetchTasks, fetchPendingQuestions, type TaskSummary, type PendingQuestion } from './api'

export interface NotificationItem {
  id: string
  kind: 'blocker' | 'done' | 'question'
  title: string
  taskId: string
  time: number
  agentId?: string
}

/** Derives notifications from the tasks list plus pending agent questions.
 * The badge count is specifically pending blockers + agent questions. */
export function useNotifications() {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [questions, setQuestions] = useState<PendingQuestion[]>([])

  useEffect(() => {
    let mounted = true
    const poll = async () => {
      try {
        const [td, qd] = await Promise.all([
          fetchTasks({ limit: 300 }),
          fetchPendingQuestions(),
        ])
        if (mounted) { setTasks(td.tasks); setQuestions(qd.questions) }
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
  const agentQuestions: NotificationItem[] = questions
    .map(q => ({
      id: `q:${q.agent_id}`,
      kind: 'question' as const,
      title: q.question,
      taskId: q.task_id || '',
      time: now,
      agentId: q.agent_id,
    }))

  const items = [...agentQuestions, ...blockers, ...recentlyDone].sort((a, b) => b.time - a.time)
  return { items, blockerCount: blockers.length + agentQuestions.length }
}
