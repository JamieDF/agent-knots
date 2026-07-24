import { useEffect, useRef, useState } from 'react'
import { subscribeToAgent, type SSEEvent } from '../../lib/sse'
import Markdown from '../../components/Markdown'
import { type EventItem, reduceEvent } from './types'

export function EventRow({ evt, collapsed, onToggleCollapse, delegateOpen, onToggleDelegate, onRevert, onOpenPreview }: {
  evt: EventItem
  collapsed: boolean
  onToggleCollapse: () => void
  delegateOpen: boolean
  onToggleDelegate: () => void
  onRevert: (label: string) => void
  onOpenPreview: (url: string) => void
}) {
  const ts = new Date(evt.timestamp * 1000)
  const tsStr = `${String(ts.getHours()).padStart(2, '0')}:${String(ts.getMinutes()).padStart(2, '0')}`

  if (evt.type === 'message') {
    return (
      <Bubble align="left" bg="var(--card2)" ts={tsStr}>
        <Markdown onLinkClick={onOpenPreview}>{evt.message}</Markdown>
      </Bubble>
    )
  }

  if (evt.type === 'thinking') {
    return (
      <div onClick={onToggleCollapse} style={{ padding: '4px 0', cursor: 'pointer' }}>
        <span style={{ fontSize: 12.5, fontStyle: 'italic', color: 'var(--mut)' }}>
          {collapsed ? '⋯ thinking — click to expand' : `⋯ ${evt.message}`}
        </span>
      </div>
    )
  }

  if (evt.type === 'tool_call' && evt.tool_call) {
    const args = Object.entries(evt.tool_call.args).map(([k, v]) => `${k}=${truncate(String(v), 60)}`).join(', ')
    return (
      <div data-testid="tool-card" style={{ margin: '6px 0 6px 36px', background: 'var(--card2)', border: '1px solid var(--line)', borderRadius: 8, padding: '8px 10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: args ? 4 : 0 }}>
          <span style={{ width: 16, height: 16, borderRadius: 4, background: 'var(--card)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: 'var(--acc)' }}>$</span>
          <span style={{ fontSize: 11.5, fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--ink2)' }}>{evt.tool_call.name}</span>
        </div>
        {args && <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)', whiteSpace: 'pre-wrap' }}>{args}</div>}
        {evt.result && (
          <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: evt.result.tool_result?.error ? 'var(--err)' : 'var(--ok)', marginTop: 4, whiteSpace: 'pre-wrap' }}>
            {truncate(evt.result.message, 300)}
          </div>
        )}
      </div>
    )
  }

  if (evt.type === 'auto_log') {
    return <div style={{ fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--mut2)', padding: '2px 0 2px 36px' }}>↳ {evt.message}</div>
  }

  if (evt.type === 'steer') {
    return (
      <div style={{ fontSize: 12, fontStyle: 'italic', color: 'var(--acc)', background: 'var(--acc-soft)', padding: '6px 10px', margin: '4px 0 4px 36px', borderRadius: 8 }}>
        ⌁ {evt.message}
      </div>
    )
  }

  if (evt.type === 'delegate') {
    const subId = evt.data?.sub_session_id as string | undefined
    const subTitle = evt.data?.title as string | undefined
    return (
      <div style={{ margin: '8px 0', border: '1px solid var(--line)', borderRadius: 10, overflow: 'hidden' }}>
        <div onClick={onToggleDelegate} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', cursor: 'pointer', background: 'var(--card2)' }}>
          <span style={{ fontSize: 10 }}>{delegateOpen ? '▾' : '▸'}</span>
          <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '0.04em', color: 'var(--acc)' }}>SUB-AGENT</span>
          <span style={{ fontSize: 12, color: 'var(--ink2)' }}>{subTitle || evt.message}</span>
          {subId && <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--mut)', marginLeft: 'auto' }}>{subId}</span>}
        </div>
        {delegateOpen && subId && <DelegateSubThread sessionId={subId} />}
      </div>
    )
  }

  if (evt.type === 'checkpoint') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '10px 0', paddingTop: 10, borderTop: '1px dashed var(--line2)' }}>
        <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mut)' }}>⚑ checkpoint · {evt.message}</span>
        <button onClick={() => onRevert(evt.message)} style={{ fontSize: 10.5, color: 'var(--acc)', fontWeight: 600 }}>revert to here</button>
      </div>
    )
  }

  if (evt.type === 'blocker' || evt.type === 'ask') {
    return (
      <Bubble align="left" bg="var(--warn-soft)" ts={tsStr}>
        <Markdown onLinkClick={onOpenPreview}>{evt.message}</Markdown>
      </Bubble>
    )
  }

  if (evt.type === 'user') {
    return (
      <Bubble align="right" bg="var(--acc-soft)" ts={tsStr}>
        <Markdown onLinkClick={onOpenPreview}>{evt.message}</Markdown>
      </Bubble>
    )
  }

  if (evt.type === 'error') {
    return (
      <Bubble align="left" ts={tsStr}>
        <span style={{ fontSize: 13, color: 'var(--err)' }}>{evt.error || evt.message}</span>
      </Bubble>
    )
  }

  if (evt.type === 'ended') {
    return <div style={{ textAlign: 'center', fontSize: 11.5, color: 'var(--mut)', padding: '12px 0', borderTop: '1px solid var(--line)', margin: '8px 0' }}>session ended</div>
  }

  // state_change / default — subtle info line.
  return <div style={{ fontSize: 11.5, color: 'var(--mut)', padding: '4px 0 4px 36px' }}>{evt.message}</div>
}

/** Chat-turn layout: agent on the left, human ("user" events) on the
 * right, like any real chat — no avatar, just alignment + a small
 * timestamp under the bubble. */
function Bubble({ align, bg, ts, children }: { align: 'left' | 'right'; bg?: string; ts: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: align === 'right' ? 'flex-end' : 'flex-start', padding: '4px 0' }}>
      <div style={{ maxWidth: '78%', padding: bg ? '8px 12px' : 0, borderRadius: 12, background: bg }}>
        {children}
      </div>
      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--mut2)', marginTop: 3, padding: bg ? '0 3px' : 0 }}>{ts}</div>
    </div>
  )
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 3) + '...' : s
}

/** Delegation cards expand into their own live mini-thread by opening a
 * separate SSE subscription to the sub-session — no server-side event
 * nesting, reusing the same infra as the top-level thread. */
function DelegateSubThread({ sessionId }: { sessionId: string }) {
  const [events, setEvents] = useState<EventItem[]>([])
  const counterRef = useRef(0)

  useEffect(() => {
    const es = subscribeToAgent(sessionId, (evt: SSEEvent) => {
      counterRef.current += 1
      setEvents(prev => reduceEvent(prev, evt, counterRef.current, 100))
    })
    return () => es.close()
  }, [sessionId])

  return (
    <div style={{ padding: '8px 12px 8px 24px', borderTop: '1px solid var(--line)' }}>
      {events.length === 0 && <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>Waiting for sub-agent events…</div>}
      {events.map(evt => (
        <div key={evt.id} style={{ fontSize: 11.5, color: 'var(--ink2)', padding: '3px 0' }}>
          {evt.type === 'message' || evt.type === 'thinking' ? evt.message : `[${evt.type}] ${evt.message || ''}`}
        </div>
      ))}
    </div>
  )
}
