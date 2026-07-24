import { useEffect, useState } from 'react'
import type { BrowserTab } from './types'

/** A small in-panel browser — real tabs, like the one on your desktop.
 * Type/paste a URL like any address bar, or click a link the agent
 * posts in chat (see Markdown's onLinkClick) and it opens in a new tab
 * here instead of leaving the app. Each tab is just an <iframe>; a site
 * that sends X-Frame-Options/CSP frame-ancestors can still refuse to
 * render inside one, which is why "open in new tab" (the real browser's)
 * is always available as an escape hatch rather than something to try
 * to detect and work around.
 *
 * Only the active tab's iframe is ever mounted — switching tabs remounts
 * it fresh at that tab's URL rather than keeping every tab's iframe
 * alive in the background. For dev-server previews (the actual use
 * case) there's no meaningful client state worth preserving across a
 * switch, so this is a deliberate simplification over a real browser's
 * per-tab process model.
 */
export function BrowserPanel({
  tabs, activeTabId, onSelectTab, onCloseTab, onNewTab, onUrlChange,
}: {
  tabs: BrowserTab[]
  activeTabId: string
  onSelectTab: (id: string) => void
  onCloseTab: (id: string) => void
  onNewTab: () => void
  onUrlChange: (tabId: string, url: string) => void
}) {
  const activeTab = tabs.find(t => t.id === activeTabId) ?? tabs[0]
  const [draft, setDraft] = useState(activeTab?.url ?? '')
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => { setDraft(activeTab?.url ?? '') }, [activeTab?.id, activeTab?.url])

  const commit = (raw: string) => {
    const trimmed = raw.trim()
    if (!trimmed || !activeTab) return
    const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`
    onUrlChange(activeTab.id, withScheme)
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '4px 4px 0', borderBottom: '1px solid var(--line)', overflowX: 'auto' }}>
        {tabs.map(t => {
          const active = t.id === activeTabId
          return (
            <div
              key={t.id}
              onClick={() => onSelectTab(t.id)}
              title={t.url || 'New Tab'}
              style={{
                display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px', borderRadius: '6px 6px 0 0',
                fontSize: 11, cursor: 'pointer', maxWidth: 140, flexShrink: 0,
                background: active ? 'var(--card2)' : 'transparent',
                color: active ? 'var(--ink)' : 'var(--mut)',
                borderBottom: active ? '2px solid var(--acc)' : '2px solid transparent',
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{browserTabLabel(t.url)}</span>
              <span
                onClick={e => { e.stopPropagation(); onCloseTab(t.id) }}
                title="Close tab"
                style={{ fontSize: 10, color: 'var(--mut)', flexShrink: 0, padding: '0 2px' }}
              >
                ✕
              </span>
            </div>
          )
        })}
        <button onClick={onNewTab} title="New tab" style={{ padding: '5px 9px', fontSize: 13, color: 'var(--mut)', flexShrink: 0 }}>+</button>
      </div>
      <div style={{ display: 'flex', gap: 6, padding: 6, borderBottom: '1px solid var(--line)' }}>
        <button
          onClick={() => setReloadKey(k => k + 1)}
          title="Reload"
          disabled={!activeTab?.url}
          style={{ padding: '4px 8px', borderRadius: 6, fontSize: 12, color: 'var(--ink2)', background: 'var(--card2)', opacity: activeTab?.url ? 1 : 0.4 }}
        >
          ⟳
        </button>
        <input
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') commit(draft) }}
          placeholder="Enter a URL to preview…"
          style={{ flex: 1, minWidth: 0, padding: '5px 8px', borderRadius: 6, border: '1px solid var(--line2)', background: 'var(--card2)', color: 'var(--ink)', fontSize: 11.5, fontFamily: 'var(--font-mono)', outline: 'none' }}
        />
        <button
          onClick={() => commit(draft)}
          style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11.5, fontWeight: 600, background: 'var(--acc)', color: 'var(--acc-ink)' }}
        >
          Go
        </button>
        <a
          href={activeTab?.url || undefined}
          target="_blank"
          rel="noreferrer"
          title="Open in new browser tab"
          style={{ padding: '4px 8px', borderRadius: 6, fontSize: 12, color: 'var(--ink2)', background: 'var(--card2)', opacity: activeTab?.url ? 1 : 0.4, pointerEvents: activeTab?.url ? 'auto' : 'none' }}
        >
          ↗
        </a>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        {activeTab?.url ? (
          <iframe
            key={`${activeTab.id}-${activeTab.url}-${reloadKey}`}
            src={activeTab.url}
            title="Browser"
            style={{ width: '100%', height: '100%', border: 'none', background: '#fff' }}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8, padding: 20, textAlign: 'center' }}>
            <div style={{ fontSize: 28, opacity: 0.3 }}>🌐</div>
            <div style={{ fontSize: 13, color: 'var(--ink2)' }}>Browser</div>
            <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>Enter a URL above, or click a link the agent posts in chat.</div>
          </div>
        )}
      </div>
    </div>
  )
}

function browserTabLabel(url: string): string {
  if (!url) return 'New Tab'
  try {
    const u = new URL(url)
    return u.hostname + (u.pathname !== '/' ? u.pathname : '')
  } catch {
    return url
  }
}
