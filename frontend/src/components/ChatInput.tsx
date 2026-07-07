import { useState, useRef, type KeyboardEvent } from 'react'

interface Props {
  onSend: (message: string) => void
  disabled?: boolean
}

function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSend = () => {
    const msg = value.trim()
    if (!msg) return
    onSend(msg)
    setValue('')
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-bar">
      <input
        ref={inputRef}
        type="text"
        placeholder={disabled ? 'Agent is not running...' : 'Send a message...'}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
      />
      <button className="btn btn-ghost" onClick={handleSend} disabled={disabled || !value.trim()}>
        Send
      </button>
    </div>
  )
}

export default ChatInput
