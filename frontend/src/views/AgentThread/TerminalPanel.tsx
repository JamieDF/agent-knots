import { useEffect, useRef, useState } from 'react'
import { useTheme } from '../../theme/ThemeContext'
import '@xterm/xterm/css/xterm.css'

// xterm.js needs literal colors, not CSS var() references, so these
// mirror index.css's --card/--ink/--acc/--acc-soft tokens directly for
// each theme rather than reading computed style — reading from the DOM
// raced with ThemeProvider's own effect (which sets
// document.body.dataset.theme): React runs child effects before parent
// effects in a commit, and ThemeProvider is an ancestor, so this
// component's effect could fire before the attribute (and the CSS
// cascade depending on it) actually updated.
const TERMINAL_THEMES: Record<'light' | 'dark', { background: string; foreground: string; cursor: string; selectionBackground: string }> = {
  light: { background: '#ffffff', foreground: '#23262b', cursor: '#6c5ce7', selectionBackground: '#f7f5ff' },
  dark: { background: '#23262d', foreground: '#dfe2e8', cursor: '#8f7ff2', selectionBackground: '#2a2740' },
}

/** Real interactive terminal — a PTY-backed shell (agent's own working
 * directory) streamed over a websocket, rendered with xterm.js. Stays
 * mounted for the lifetime of the Agent Thread (see the parent's
 * always-mounted-but-hidden wrapper) so switching tabs doesn't kill the
 * shell's state (cwd, exported vars, a still-running command). */
export function TerminalPanel({ agentId, active }: { agentId?: string; active: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<InstanceType<typeof import('@xterm/xterm').Terminal> | null>(null)
  const fitRef = useRef<InstanceType<typeof import('@xterm/addon-fit').FitAddon> | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed'>('connecting')
  const { theme } = useTheme()

  useEffect(() => {
    if (!agentId || !containerRef.current) return
    let disposed = false

    Promise.all([import('@xterm/xterm'), import('@xterm/addon-fit')]).then(([{ Terminal }, { FitAddon }]) => {
      if (disposed || !containerRef.current) return

      const term = new Terminal({
        fontFamily: '"DM Mono", var(--font-mono), monospace',
        fontSize: 12,
        cursorBlink: true,
        theme: TERMINAL_THEMES[theme],
      })
      const fit = new FitAddon()
      term.loadAddon(fit)
      term.open(containerRef.current)
      try { fit.fit() } catch { /* container may still be 0x0 on first paint */ }
      termRef.current = term
      fitRef.current = fit

      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${window.location.host}/api/agent/${agentId}/terminal`)
      wsRef.current = ws

      ws.onopen = () => {
        setStatus('open')
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
      ws.onclose = () => setStatus('closed')
      ws.onerror = () => setStatus('closed')
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'output') term.write(msg.data)
        } catch { /* ignore malformed frames */ }
      }

      const dataDisposable = term.onData(data => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data }))
      })

      const resizeObserver = new ResizeObserver(() => {
        if (!active) return // avoid fitting a 0x0 hidden container
        try { fit.fit() } catch { return }
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      })
      resizeObserver.observe(containerRef.current)

      return () => {
        dataDisposable.dispose()
        resizeObserver.disconnect()
        ws.close()
        term.dispose()
      }
    })

    return () => { disposed = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId])

  // The container is 0x0 while display:none (hidden tab) — re-fit once
  // it actually becomes visible, or xterm renders at a stale/wrong size.
  useEffect(() => {
    if (active && fitRef.current && wsRef.current) {
      try { fitRef.current.fit() } catch { return }
      const term = termRef.current
      if (term && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
    }
  }, [active])

  // xterm's theme is a snapshot taken once at creation — toggling
  // light/dark afterward otherwise leaves the terminal visually stuck
  // on whichever theme was active when it first connected.
  useEffect(() => {
    if (termRef.current) termRef.current.options.theme = TERMINAL_THEMES[theme]
  }, [theme])

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '4px 10px', fontSize: 10, color: 'var(--mut)', borderBottom: '1px solid var(--line)', fontFamily: 'var(--font-mono)' }}>
        {status === 'open' ? '● connected' : status === 'connecting' ? '○ connecting…' : '○ disconnected'}
      </div>
      <div ref={containerRef} style={{ flex: 1, minHeight: 0, padding: 4 }} />
    </div>
  )
}
