import { Navigate } from 'react-router-dom'
import { PhoneApp } from './PhoneApp'
import { Connect } from './screens/Connect'
import { Health } from './screens/Health'
import { Me } from './screens/Me'
import { Plan } from './screens/Plan'
import { SessionScreen } from './screens/Session'
import { SportHistory } from './screens/SportHistory'
import { Today } from './screens/Today'
import { Trends } from './screens/Trends'
import { VerdictScreen } from './screens/Verdict'

export const phoneRoutes = [
  {
    path: '/',
    element: <PhoneApp />,
    children: [
      { index: true, element: <Today /> },
      { path: 'plan', element: <Plan /> },
      { path: 'trends', element: <Trends /> },
      { path: 'trends/health', element: <Health /> },
      { path: 'trends/sport/:sport', element: <SportHistory /> },
      { path: 'me', element: <Me /> },
      { path: 'me/connect', element: <Connect /> },
      { path: 'verdict/:id', element: <VerdictScreen /> },
      { path: 'session/:id', element: <SessionScreen /> },
      { path: '*', element: <Navigate to="/" replace /> },  // the wall's own pages (/u/…, /accounts)
    ],
  },
]
