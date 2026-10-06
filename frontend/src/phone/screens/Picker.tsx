import { Smartphone, Zap } from 'lucide-react'
import type { User } from '../../api'

/** First open on a phone: pick yourself once. Stored on this phone only — the wall isn't affected. */
export function Picker({ users, onPick }: { users: User[]; onPick: (id: string) => void }) {
  return (
    <div className="ph ph-page ph-solo">
      <div className="ph-brand"><Zap size={26} color="var(--volt)" strokeWidth={2.2} aria-hidden /> FITVIO</div>
      <h1 className="ph-title" style={{ color: 'var(--volt)' }}>Who are you?</h1>
      <p className="ph-sub">Pick yourself once. This phone will open on your training.</p>
      <div className="ph-pick">
        {users.map(u => (
          <button key={u.id} className="ph-person" onClick={() => onPick(u.id)}>
            <span className="ph-avatar xl" style={{ borderColor: u.color }}>{u.initials}</span>
            <span className="ph-person-name">{u.name}</span>
          </button>
        ))}
      </div>
      <p className="ph-note"><Smartphone size={18} aria-hidden />Remembered on this phone. You can switch later under Me — the wall isn’t affected.</p>
    </div>
  )
}
