import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter, Routes, Route } from 'react-router-dom'
import App from './App'
import Overview from './views/Overview'
import AgentFocus from './views/AgentFocus'
import Tasks from './views/Tasks'
import Board from './views/Board'
import TaskDetail from './views/TaskDetail'
import ToolManager from './views/ToolManager'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <HashRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Overview />} />
          <Route path="agent/:id" element={<AgentFocus />} />
          <Route path="board" element={<Board />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="tasks/:id" element={<TaskDetail />} />
          <Route path="tools" element={<ToolManager />} />
        </Route>
      </Routes>
    </HashRouter>
  </StrictMode>,
)
