import { useApp } from '../App'
import { ConnectForm } from '../components/ConnectForm'
import { WallAmbient } from './WallAmbient'
import { WallVerdict } from './WallVerdict'

export function Wall() {
  const { wall, reload } = useApp()
  if (!wall || wall.mode === 'setup') {
    return (
      <div className="card" style={{ maxWidth: 640, margin: 'calc(var(--vh) * 6) auto' }}>
        <h1 style={{ marginTop: 0, fontSize: 30 }}>Welcome to your Health Wall</h1>
        <p className="muted" style={{ marginTop: 0 }}>
          Connect your Garmin account. Your whole history is downloaded and every activity gets a verdict —
          did it make you better?
        </p>
        <ConnectForm onDone={reload} resume={wall?.mode === 'setup' ? wall.job : null} />
      </div>
    )
  }
  if (wall.mode === 'verdict') return <WallVerdict session={wall.session} ambient={wall.ambient} />
  return <WallAmbient ambient={wall.ambient} />
}
