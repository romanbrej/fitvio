import { useNavigate } from 'react-router-dom'
import { ConnectForm } from '../../components/ConnectForm'
import { usePhone } from '../ctx'
import { Back } from '../parts'

export function Connect() {
  const { reloadConfig } = usePhone()
  const nav = useNavigate()
  return (
    <div className="ph-stack">
      <Back to="/me" label="Me" />
      <h1 className="ph-title">Add a person</h1>
      <p className="ph-secondary" style={{ margin: 0 }}>Connect their Garmin or Intervals.icu account. Their whole history is downloaded on the server.</p>
      <ConnectForm onDone={() => { reloadConfig(); nav('/me') }} />
    </div>
  )
}
