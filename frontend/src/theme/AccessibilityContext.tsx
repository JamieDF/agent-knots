import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type FontFamilyKey = 'default' | 'system' | 'accessible'

export const FONT_FAMILIES: Record<FontFamilyKey, { label: string; stack: string }> = {
  default: { label: 'Default (DM Sans)', stack: "'DM Sans', system-ui, sans-serif" },
  system: { label: 'System font', stack: '-apple-system, system-ui, sans-serif' },
  accessible: { label: 'Atkinson Hyperlegible (accessible)', stack: "'Atkinson Hyperlegible', system-ui, sans-serif" },
}

export const FONT_SCALES = [0.875, 1, 1.125, 1.25, 1.375] as const
export type FontScale = (typeof FONT_SCALES)[number]

export type ContentWidthKey = 'compact' | 'comfortable' | 'wide'

export const CONTENT_WIDTHS: Record<ContentWidthKey, { label: string; value: string }> = {
  compact: { label: 'Compact', value: 'min(820px, calc(100vw - 40px))' },
  comfortable: { label: 'Comfortable', value: 'min(1000px, calc(100vw - 40px))' },
  wide: { label: 'Wide', value: 'min(1200px, calc(100vw - 40px))' },
}

const SCALE_KEY = 'agent-knots-font-scale'
const FAMILY_KEY = 'agent-knots-font-family'
const WIDTH_KEY = 'agent-knots-content-width'

interface AccessibilityContextValue {
  fontScale: FontScale
  setFontScale: (scale: FontScale) => void
  fontFamily: FontFamilyKey
  setFontFamily: (family: FontFamilyKey) => void
  contentWidth: ContentWidthKey
  setContentWidth: (width: ContentWidthKey) => void
}

const AccessibilityContext = createContext<AccessibilityContextValue | null>(null)

function getStoredScale(): FontScale {
  const stored = Number(localStorage.getItem(SCALE_KEY))
  return (FONT_SCALES as readonly number[]).includes(stored) ? (stored as FontScale) : 1
}

function getStoredFamily(): FontFamilyKey {
  const stored = localStorage.getItem(FAMILY_KEY)
  return stored && stored in FONT_FAMILIES ? (stored as FontFamilyKey) : 'default'
}

function getStoredContentWidth(): ContentWidthKey {
  const stored = localStorage.getItem(WIDTH_KEY)
  return stored && stored in CONTENT_WIDTHS ? (stored as ContentWidthKey) : 'comfortable'
}

/** Text size and font family, applied globally rather than per-component.
 *
 * Font *family* is one CSS variable (--font) that everything already
 * inherits from body's own font shorthand — a single update there is
 * enough. Font *size* is a much bigger problem: the whole app hand-sets
 * pixel fontSize values inline per component rather than using rem/em
 * units, so there's no single CSS variable that would rescale them all.
 * Rewriting every inline style to rem across the whole codebase is the
 * "correct" fix but a large, risky one; `zoom` on the root element scales
 * the fully-rendered layout (text, spacing, icons) proportionally without
 * touching a single component, at the cost of being a non-standard
 * property (though shipped in all major browsers now, including Firefox
 * 126+). Pragmatic tradeoff for a local-first single-user tool.
 */
export function AccessibilityProvider({ children }: { children: ReactNode }) {
  const [fontScale, setFontScale] = useState<FontScale>(getStoredScale)
  const [fontFamily, setFontFamily] = useState<FontFamilyKey>(getStoredFamily)
  const [contentWidth, setContentWidth] = useState<ContentWidthKey>(getStoredContentWidth)

  useEffect(() => {
    const root = document.getElementById('root')
    if (root) root.style.setProperty('zoom', String(fontScale))
    localStorage.setItem(SCALE_KEY, String(fontScale))
  }, [fontScale])

  useEffect(() => {
    document.body.style.setProperty('--font', FONT_FAMILIES[fontFamily].stack)
    localStorage.setItem(FAMILY_KEY, fontFamily)
  }, [fontFamily])

  useEffect(() => {
    document.body.style.setProperty('--content-width', CONTENT_WIDTHS[contentWidth].value)
    localStorage.setItem(WIDTH_KEY, contentWidth)
  }, [contentWidth])

  return (
    <AccessibilityContext.Provider value={{ fontScale, setFontScale, fontFamily, setFontFamily, contentWidth, setContentWidth }}>
      {children}
    </AccessibilityContext.Provider>
  )
}

export function useAccessibility(): AccessibilityContextValue {
  const ctx = useContext(AccessibilityContext)
  if (!ctx) throw new Error('useAccessibility must be used within an AccessibilityProvider')
  return ctx
}
