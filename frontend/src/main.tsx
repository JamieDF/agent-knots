import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import App from './App'
import Dashboard from './views/Dashboard'
import AgentThread from './views/AgentThread'
import Tasks from './views/Tasks'
import TaskDetail from './views/TaskDetail'
import Review from './views/Review'
import Workflows from './views/Workflows'
import SettingsPage from './views/Settings'
import './index.css'

// AgentThread keeps events/agent/task/etc. as local state fetched per
// session id — navigating from one thread straight to another (e.g.
// starting a new session while already viewing one) hits the same
// route element, so React doesn't remount it and the previous
// session's stale messages/state sit there until new data trickles
// in, looking like the new session "didn't open". Keying by :id
// forces a clean remount whenever it changes.
function AgentThreadRoute() {
  const { id } = useParams<{ id: string }>()
  return <AgentThread key={id} />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Dashboard />} />
          <Route path="agent/:id" element={<AgentThreadRoute />} />
          {/* /board merged into the Tasks screen's Board tab —
              redirect so old bookmarks/links still land somewhere real. */}
          <Route path="board" element={<Navigate to="/tasks?view=board" replace />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="tasks/:id" element={<TaskDetail />} />
          <Route path="review" element={<Review />} />
          <Route path="review/:id" element={<Review />} />
          <Route path="workflows" element={<Workflows />} />
          {/* Vault folded into a Settings section (jump-to via the side
              nav's #vault anchor) instead of its own top-nav screen. */}
          <Route path="vault" element={<Navigate to="/settings#vault" replace />} />
          {/* ToolManager.tsx was a confirmed exact duplicate of Settings'
              own Tools section (same API, same functionality, never
              linked from the topbar nav) — deleted rather than kept as
              a second implementation of the same screen. */}
          <Route path="tools" element={<Navigate to="/settings#tools" replace />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
