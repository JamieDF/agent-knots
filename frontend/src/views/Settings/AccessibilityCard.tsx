import { Card, Field, SectionLabel, inputStyle } from '../../components/primitives'
import { useAccessibility, FONT_FAMILIES, FONT_SCALES, type FontFamilyKey, type FontScale } from '../../theme/AccessibilityContext'

const FONT_SCALE_LABELS: Record<FontScale, string> = {
  0.875: 'Small',
  1: 'Default',
  1.125: 'Large',
  1.25: 'Larger',
  1.375: 'Largest',
}

export function AccessibilityCard() {
  const { fontScale, setFontScale, fontFamily, setFontFamily } = useAccessibility()

  return (
    <Card>
      <SectionLabel>Accessibility</SectionLabel>
      <div style={{ fontSize: 11.5, color: 'var(--mut)', margin: '4px 0 14px' }}>
        Applies everywhere in the app, saved to this browser.
      </div>

      <Field label="Text size">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {FONT_SCALES.map(scale => (
            <button
              key={scale}
              onClick={() => setFontScale(scale)}
              style={{
                padding: '6px 12px', borderRadius: 8, fontSize: 12.5, fontWeight: 600,
                background: fontScale === scale ? 'var(--acc)' : 'var(--card2)',
                color: fontScale === scale ? 'var(--acc-ink)' : 'var(--ink2)',
              }}
            >
              {FONT_SCALE_LABELS[scale]}
            </button>
          ))}
        </div>
      </Field>

      <div style={{ height: 14 }} />

      <Field label="Font">
        <select
          aria-label="Font family"
          value={fontFamily}
          onChange={e => setFontFamily(e.target.value as FontFamilyKey)}
          style={inputStyle}
        >
          {(Object.keys(FONT_FAMILIES) as FontFamilyKey[]).map(key => (
            <option key={key} value={key}>{FONT_FAMILIES[key].label}</option>
          ))}
        </select>
      </Field>
    </Card>
  )
}
