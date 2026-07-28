import { useEffect, useState, useCallback, useRef, useLayoutEffect } from 'react'
import { useLocation } from 'react-router-dom'
import DeskLayout from '../../components/DeskLayout'
import { AccessibilityCard } from './AccessibilityCard'
import { IntegrationsCard } from './IntegrationsCard'
import { McpServersCard } from './McpServersCard'
import { PoliciesCard } from './PoliciesCard'
import { ProvidersCard } from './ProvidersCard'
import { ToolsCard } from './ToolsCard'
import { UsageCard } from './UsageCard'
import { VaultCard } from './VaultCard'
import { WastebinCard } from './WastebinCard'
import { WorkspacesCard } from './WorkspacesCard'

const SECTIONS = [
  { id: 'usage', label: 'Usage' },
  { id: 'accessibility', label: 'Accessibility' },
  { id: 'providers', label: 'Model providers' },
  { id: 'tools', label: 'Tools' },
  { id: 'policies', label: 'Policies' },
  { id: 'mcp', label: 'MCP servers' },
  { id: 'integrations', label: 'Integrations' },
  { id: 'vault', label: 'Vault' },
  { id: 'workspaces', label: 'Workspaces' },
  { id: 'wastebin', label: 'Wastebin' },
]

/** Settings screen — a scrolling column of cards (one per SECTIONS
 * entry), with a sticky side nav for jumping between them directly
 * since the page has grown long enough that scrolling to a specific
 * card by hand is tedious. */
function SettingsPage() {
  const location = useLocation()
  const scrollRef = useRef<HTMLDivElement>(null)
  const [activeId, setActiveId] = useState(SECTIONS[0].id)

  const scrollToSection = useCallback((id: string, smooth = true) => {
    const el = document.getElementById(id)
    el?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' })
  }, [])

  // Land on the right section when arriving via a #hash (bookmark, or
  // the /vault -> /settings#vault redirect for the old standalone route).
  // Every card fetches its own data on mount, so the page's layout keeps
  // shifting for a beat after first paint — one scrollIntoView right away
  // gets shoved out from under itself as later cards finish loading and
  // grow taller. Re-correct a few times as things settle instead of once.
  useLayoutEffect(() => {
    const id = location.hash.replace(/^#/, '')
    if (id && SECTIONS.some(s => s.id === id)) {
      setActiveId(id)
      const timers = [0, 150, 400, 900].map(delay =>
        window.setTimeout(() => scrollToSection(id, false), delay)
      )
      return () => timers.forEach(clearTimeout)
    }
    // Only on mount / hash change — not on every scroll-driven activeId update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.hash])

  // Scroll-spy: whichever section's top has crossed closest above the
  // container's top edge is the "current" one.
  useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    let raf = 0
    const onScroll = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const containerTop = container.getBoundingClientRect().top
        let current = SECTIONS[0].id
        for (const s of SECTIONS) {
          const el = document.getElementById(s.id)
          if (!el) continue
          if (el.getBoundingClientRect().top - containerTop <= 80) current = s.id
        }
        setActiveId(current)
      })
    }
    container.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => { container.removeEventListener('scroll', onScroll); cancelAnimationFrame(raf) }
  }, [])

  return (
    <DeskLayout width={1040} ref={scrollRef}>
      <div style={{ display: 'flex', gap: 28, alignItems: 'flex-start' }}>
        <nav style={{ position: 'sticky', top: 0, width: 150, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {SECTIONS.map(s => (
            <button
              key={s.id}
              onClick={() => scrollToSection(s.id)}
              style={{
                textAlign: 'left', padding: '6px 10px', borderRadius: 8, fontSize: 12.5, fontWeight: 600,
                color: activeId === s.id ? 'var(--acc)' : 'var(--ink2)',
                background: activeId === s.id ? 'var(--acc-soft)' : 'transparent',
              }}
            >
              {s.label}
            </button>
          ))}
        </nav>

        <div style={{ flex: 1, minWidth: 0, maxWidth: 800 }}>
          <Section id="usage"><UsageCard /></Section>
          <Section id="accessibility"><AccessibilityCard /></Section>
          <Section id="providers"><ProvidersCard /></Section>
          <Section id="tools"><ToolsCard /></Section>
          <Section id="policies"><PoliciesCard /></Section>
          <Section id="mcp"><McpServersCard /></Section>
          <Section id="integrations"><IntegrationsCard /></Section>
          <Section id="vault"><VaultCard /></Section>
          <Section id="workspaces"><WorkspacesCard /></Section>
          <Section id="wastebin" last><WastebinCard /></Section>
          {/* Without trailing space, a short last section (or two) can
              never scroll flush to the container's top — there just isn't
              enough content below it to push it up that far. That leaves
              the side nav's active-highlight visibly stuck on an earlier
              section whenever you jump to one of these. */}
          <div style={{ height: '70vh' }} />
        </div>
      </div>
    </DeskLayout>
  )
}

function Section({ id, last, children }: { id: string; last?: boolean; children: React.ReactNode }) {
  return (
    <div id={id} style={{ scrollMarginTop: 16, marginBottom: last ? 0 : 16 }}>
      {children}
    </div>
  )
}

export default SettingsPage
