import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter, Routes, Route } from 'react-router-dom'
import App from './App'
import Overview from './views/Overview'
import AgentFocus from './views/AgentFocus'
import Tasks from './views/Tasks'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <HashRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Overview />} />
          <Route path="agent/:id" element={<AgentFocus />} />
          <Route path="tasks" element={<Tasks />} />
        </Route>
      </Routes>
    </HashRouter>
  </StrictMode>,
)
