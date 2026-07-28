/** Status → color/glyph map covering draft · open · planned ·
 * in_progress · blocked · review · done · abandoned. Single source of
 * truth — don't hand-roll per-view status color dicts (Board.tsx and
 * TaskDetail.tsx used to each have their own, slightly inconsistent,
 * copy of this). */

export interface StatusStyle {
  color: string
  glyph: string
  label: string
}

export const STATUS_STYLES: Record<string, StatusStyle> = {
  draft: { color: 'var(--mut2)', glyph: '○', label: 'Draft' },
  open: { color: 'var(--ink2)', glyph: '◌', label: 'Open' },
  planned: { color: 'var(--acc)', glyph: '◔', label: 'Planned' },
  in_progress: { color: 'var(--ok)', glyph: '●', label: 'In progress' },
  blocked: { color: 'var(--warn-ink)', glyph: '⚠', label: 'Blocked' },
  review: { color: '#a06be0', glyph: '◉', label: 'Review' },
  done: { color: 'var(--ok)', glyph: '✓', label: 'Done' },
  abandoned: { color: 'var(--mut2)', glyph: '✕', label: 'Abandoned' },
}

export function statusStyle(status: string): StatusStyle {
  return STATUS_STYLES[status] ?? { color: 'var(--mut)', glyph: '○', label: status }
}
