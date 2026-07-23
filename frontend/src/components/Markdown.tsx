import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { CSSProperties } from 'react'

interface Props {
  children: string
  fontSize?: number
  color?: string
  /** If given, links render as clickable buttons that call this instead
   * of opening a new tab — used in chat bubbles so an agent-mentioned
   * URL (e.g. a dev server it just started) opens straight into the
   * Preview tab instead of leaving the app. remark-gfm autolinks bare
   * URLs in plain text too, so this covers "http://localhost:5173"
   * typed as-is, not just markdown [link](url) syntax. */
  onLinkClick?: (href: string) => void
}

/** Renders agent/user chat text as markdown (bold, lists, code blocks,
 * links, tables) with the Atelier design tokens instead of raw
 * asterisks/backticks — plain text still renders exactly as plain
 * text, this only kicks in when the content actually has markdown. */
function Markdown({ children, fontSize = 13, color = 'var(--ink)', onLinkClick }: Props) {
  return (
    <div style={{ fontSize, color, lineHeight: 1.55 }} className="md-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p style={{ margin: '0 0 8px' }}>{children}</p>,
          ul: ({ children }) => <ul style={{ margin: '0 0 8px', paddingLeft: 20 }}>{children}</ul>,
          ol: ({ children }) => <ol style={{ margin: '0 0 8px', paddingLeft: 20 }}>{children}</ol>,
          li: ({ children }) => <li style={{ margin: '2px 0' }}>{children}</li>,
          a: ({ children, href }) => (
            <a
              href={href}
              target={onLinkClick ? undefined : '_blank'}
              rel="noreferrer"
              onClick={onLinkClick && href ? (e) => { e.preventDefault(); onLinkClick(href) } : undefined}
              style={{ color: 'var(--acc)', cursor: 'pointer' }}
            >
              {children}
            </a>
          ),
          strong: ({ children }) => <strong style={{ fontWeight: 700 }}>{children}</strong>,
          em: ({ children }) => <em>{children}</em>,
          blockquote: ({ children }) => (
            <blockquote style={{ margin: '0 0 8px', padding: '2px 12px', borderLeft: '3px solid var(--line2)', color: 'var(--ink2)' }}>{children}</blockquote>
          ),
          h1: ({ children }) => <div style={{ fontSize: fontSize + 4, fontWeight: 700, margin: '4px 0 8px' }}>{children}</div>,
          h2: ({ children }) => <div style={{ fontSize: fontSize + 3, fontWeight: 700, margin: '4px 0 8px' }}>{children}</div>,
          h3: ({ children }) => <div style={{ fontSize: fontSize + 1.5, fontWeight: 700, margin: '4px 0 6px' }}>{children}</div>,
          hr: () => <hr style={{ border: 0, borderTop: '1px solid var(--line)', margin: '8px 0' }} />,
          table: ({ children }) => (
            <div style={{ overflowX: 'auto', margin: '0 0 8px' }}>
              <table style={{ borderCollapse: 'collapse', fontSize: fontSize - 1 }}>{children}</table>
            </div>
          ),
          th: ({ children }) => <th style={cellStyle(true)}>{children}</th>,
          td: ({ children }) => <td style={cellStyle(false)}>{children}</td>,
          code: (props) => {
            const { className, children, ...rest } = props as { className?: string; children?: React.ReactNode; inline?: boolean }
            const isInline = (props as { inline?: boolean }).inline ?? !className
            if (isInline) {
              return (
                <code
                  style={{
                    fontFamily: 'var(--font-mono)', fontSize: fontSize - 1, background: 'var(--mono-bg)',
                    padding: '1px 5px', borderRadius: 4,
                  }}
                  {...rest}
                >
                  {children}
                </code>
              )
            }
            return (
              // index.css has a global `code { background; padding; border-radius }`
              // rule (for inline code elsewhere in the app) — without explicitly
              // zeroing those out here, it leaks into block code too, since inline
              // `style` only overrides properties it actually sets.
              <code
                className={className}
                style={{ fontFamily: 'var(--font-mono)', fontSize: fontSize - 1, background: 'transparent', padding: 0, borderRadius: 0 }}
                {...rest}
              >
                {children}
              </code>
            )
          },
          pre: ({ children }) => (
            <pre
              style={{
                background: 'var(--mono-bg)', border: '1px solid var(--line)', borderRadius: 8,
                padding: '10px 12px', margin: '0 0 8px', overflowX: 'auto', whiteSpace: 'pre',
              }}
            >
              {children}
            </pre>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}

function cellStyle(header: boolean): CSSProperties {
  return {
    border: '1px solid var(--line)', padding: '4px 8px', textAlign: 'left',
    fontWeight: header ? 700 : 400, background: header ? 'var(--card2)' : undefined,
  }
}

export default Markdown
