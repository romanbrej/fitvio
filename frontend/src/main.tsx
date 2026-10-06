import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import App from './App'
import './theme.css'
import { Accounts } from './views/Accounts'
import { HealthDetail } from './views/HealthDetail'
import { LoadDetail } from './views/LoadDetail'
import { PlanDetail } from './views/PlanDetail'
import { SessionDetailView } from './views/SessionDetail'
import { SportDetail } from './views/SportDetail'
import { ValidationDetail } from './views/ValidationDetail'
import { Wall } from './views/Wall'

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Wall /> },
      { path: 'accounts', element: <Accounts /> },
      { path: 'session/:id', element: <SessionDetailView /> },
      { path: 'u/:user/load', element: <LoadDetail /> },
      { path: 'u/:user/health/:metric', element: <HealthDetail /> },
      { path: 'u/:user/sport/:sport', element: <SportDetail /> },
      { path: 'u/:user/validation', element: <ValidationDetail /> },
      { path: 'u/:user/plan', element: <PlanDetail /> },
      { path: 'u/:user/today', element: <Navigate to="../plan" relative="path" replace /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
