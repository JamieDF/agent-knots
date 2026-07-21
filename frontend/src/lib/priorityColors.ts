/** Priority → color map, from design_handoff_atelier_cockpit/README.md
 * ("Priority: URGENT err, HIGH warn-ink, MED acc, LOW mut"). */

export const PRIORITY_COLORS: Record<string, string> = {
  urgent: 'var(--err)',
  high: 'var(--warn-ink)',
  medium: 'var(--acc)',
  low: 'var(--mut)',
}

export function priorityColor(priority: string): string {
  return PRIORITY_COLORS[priority] ?? 'var(--mut)'
}
