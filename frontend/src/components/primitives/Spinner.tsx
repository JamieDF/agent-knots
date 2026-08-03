/** Circular loading indicator — a bare rotating-border ring, no
 * dependency beyond the `knots-spin` keyframes in index.css (inline
 * styles can't declare @keyframes themselves). Used anywhere a screen
 * has nothing meaningful to show yet and needs to say so, rather than
 * silently rendering an empty state that's indistinguishable from
 * "there's genuinely nothing here." */
function Spinner({ size = 20 }: { size?: number }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        border: `${Math.max(2, size / 8)}px solid var(--line2)`,
        borderTopColor: 'var(--acc)',
        animation: 'knots-spin 0.7s linear infinite',
      }}
    />
  )
}

export default Spinner
