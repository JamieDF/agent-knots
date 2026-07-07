import { useNavigate } from 'react-router-dom'
import type { AgentInfo } from '../lib/api'
import { deleteAgent } from '../lib/api'

interface Props {
  agent: AgentInfo
  onDelete: () => void
}

function AgentCard({ agent, onDelete }: Props) {
  const navigate = useNavigate()

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation()
    await deleteAgent(agent.id)
    onDelete()
  }

  return (
    <div className="agent-card" onClick={() => navigate(`/agent/${agent.id}`)} style={{ position: 'relative' }}>
      <div className="agent-card-header">
        <div className={`status-pip ${agent.running ? 'running' : ''}`} />
        <div className={`mode-pill ${agent.mode === 'assistant' ? 'assumed' : ''}`}>
          <span className="pill-dot" />
          {agent.mode === 'assistant' ? 'driving' : agent.mode}
        </div>
        <button
          onClick={handleDelete}
          title="Delete agent"
          style={{
            marginLeft: 'auto', width: 20, height: 20, borderRadius: 4,
            border: '1px solid transparent', background: 'transparent',
            color: 'var(--muted-2)', fontSize: 12, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--blocked)'; (e.currentTarget as HTMLElement).style.color = 'var(--blocked)' }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'transparent'; (e.currentTarget as HTMLElement).style.color = 'var(--muted-2)' }}
        >✕</button>
      </div>
      <div className="agent-card-id">{agent.id}</div>
      <div className="agent-card-action">{agent.running ? 'running...' : 'idle'}</div>
      <div className="agent-card-stats">
        <span>{agent.tokens_used.toLocaleString()} tok</span>
        <span>${agent.cost_usd.toFixed(3)}</span>
      </div>
    </div>
  )
}

export default AgentCard
