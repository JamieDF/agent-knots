/** Shared display-formatting helpers.
 *
 * timeAgo() was independently reimplemented in TaskDetail.tsx (as
 * `rel`), NotificationBell.tsx, and Settings.tsx — found in a
 * full-codebase review. priorityColors.ts/statusColors.ts already went
 * through this exact consolidation; this is the one that got missed.
 */

/** Relative time like "3m ago" / "2h ago" / "5d ago", from a Unix
 * timestamp in seconds (matches the backend's time.time() convention).
 * Pass emptyLabel to return it for a falsy timestamp (0/undefined)
 * instead of computing "just now" for it — useful for "hasn't happened
 * yet" fields. */
export function timeAgo(ts: number, emptyLabel?: string): string {
  if (!ts && emptyLabel !== undefined) return emptyLabel
  const s = Date.now() / 1000 - ts
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}
