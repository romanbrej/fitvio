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
      <h1 className="ph-title">Connect Garmin</h1>
      <p className="ph-secondary" style={{ margin: 0 }}>Add a person with their Garmin login. Their whole history is downloaded on the server.</p>
      <ConnectForm onDone={() => { reloadConfig(); nav('/me') }} />
    </div>
  )
}
