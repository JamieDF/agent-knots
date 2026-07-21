import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import App from './App'
import Dashboard from './views/Dashboard'
import AgentThread from './views/AgentThread'
import Tasks from './views/Tasks'
import TaskDetail from './views/TaskDetail'
import Review from './views/Review'
import Workflows from './views/Workflows'
import Vault from './views/Vault'
import ToolManager from './views/ToolManager'
import SettingsPage from './views/Settings'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Dashboard />} />
          <Route path="agent/:id" element={<AgentThread />} />
          {/* /board merged into the Tasks screen's Board tab (Phase 1) —
              redirect so old bookmarks/links still land somewhere real. */}
          <Route path="board" element={<Navigate to="/tasks?view=board" replace />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="tasks/:id" element={<TaskDetail />} />
          <Route path="review" element={<Review />} />
          <Route path="workflows" element={<Workflows />} />
          <Route path="vault" element={<Vault />} />
          <Route path="tools" element={<ToolManager />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
