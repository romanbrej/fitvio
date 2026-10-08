import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, createHashRouter, Navigate, RouterProvider } from 'react-router-dom'
import App from './App'
import { DEMO } from './demo/demo'
import { DemoShell } from './demo/DemoShell'
import './theme.css'
import { applyUiScale } from './uiScale'
import { isPhone, reloadWhenPhoneChanges } from './phone/isPhone'
import { phoneRoutes } from './phone/routes'
import { Accounts } from './views/Accounts'
import { HealthDetail } from './views/HealthDetail'
import { LoadDetail } from './views/LoadDetail'
import { PlanDetail } from './views/PlanDetail'
import { SessionDetailView } from './views/SessionDetail'
import { SportDetail } from './views/SportDetail'
import { ValidationDetail } from './views/ValidationDetail'
import { Wall } from './views/Wall'

const wallRoutes = [
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
]

const root = createRoot(document.getElementById('root')!)

if (DEMO && !new URLSearchParams(window.location.search).has('app')) {
  // the demo page (landing + wall/phone switch); the app runs inside it in a device-sized frame
  root.render(<StrictMode><DemoShell /></StrictMode>)
} else {
  if (DEMO) document.documentElement.dataset.demo = ''
  // A phone gets the personal companion app; everything else (the wall tablet, laptops) the wall.
  const phone = isPhone()
  reloadWhenPhoneChanges(phone)
  if (!phone) applyUiScale()
  // the demo is static files on GitHub Pages: hash URLs work on any path without a server
  const router = (DEMO ? createHashRouter : createBrowserRouter)(phone ? phoneRoutes : wallRoutes)
  root.render(
    <StrictMode>
      <RouterProvider router={router} />
    </StrictMode>,
  )
}
