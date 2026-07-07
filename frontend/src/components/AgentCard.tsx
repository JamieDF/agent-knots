import { useNavigate } from 'react-router-dom'
import type { AgentInfo } from '../lib/api'

interface Props {
  agent: AgentInfo
}

function AgentCard({ agent }: Props) {
  const navigate = useNavigate()

  return (
    <div
      className="agent-card"
      onClick={() => navigate(`/agent/${agent.id}`)}
    >
      <div className="agent-card-header">
        <div className={`status-pip ${agent.running ? 'running' : ''}`} />
        <div className={`mode-pill ${agent.mode === 'assistant' ? 'assumed' : ''}`}>
          <span className="pill-dot" />
          {agent.mode === 'assistant' ? 'driving' : agent.mode}
        </div>
      </div>
      <div className="agent-card-id">{agent.id}</div>
      <div className="agent-card-action">
        {agent.running ? 'running...' : 'idle'}
      </div>
      <div className="agent-card-stats">
        <span>{agent.tokens_used.toLocaleString()} tok</span>
        <span>${agent.cost_usd.toFixed(3)}</span>
      </div>
    </div>
  )
}

export default AgentCard
