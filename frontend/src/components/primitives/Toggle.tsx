interface Props {
  checked: boolean
  onChange: (checked: boolean) => void
  small?: boolean
  disabled?: boolean
}

/** Atelier's on/off switch — 36x20 (32x18 small), 16px knob. */
function Toggle({ checked, onChange, small, disabled }: Props) {
  const width = small ? 32 : 36
  const height = small ? 18 : 20
  const knob = 16
  const pad = (height - knob) / 2

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        width,
        height,
        borderRadius: height / 2,
        background: checked ? 'var(--acc)' : 'var(--line2)',
        position: 'relative',
        padding: 0,
        transition: 'background 0.15s',
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: 'absolute',
          top: pad,
          left: checked ? width - knob - pad : pad,
          width: knob,
          height: knob,
          borderRadius: '50%',
          background: '#fff',
          boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
          transition: 'left 0.15s',
        }}
      />
    </button>
  )
}

export default Toggle
