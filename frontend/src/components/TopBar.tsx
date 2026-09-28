import { ChevronLeft, CloudOff, RefreshCw, UserCog } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { SyncInfo, User } from '../api'
import { ago } from '../format'
import './TopBar.css'

export function TopBar({ users, activeUser, onSelect, sync }: {
  users: User[]; activeUser: string | null; onSelect: (id: string) => void; sync: SyncInfo | null
}) {
  const [now, setNow] = useState(new Date())
  const nav = useNavigate()
  const loc = useLocation()
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 15000)
    return () => clearInterval(t)
  }, [])
  const onWall = loc.pathname === '/'

  return (
    <header className="topbar">
      <div className="topbar-left">
        {!onWall && (
          <button className="btn" onClick={() => nav('/')} aria-label="Back to wall">
            <ChevronLeft size={22} /> Wall
          </button>
        )}
        <div className="avatars" role="tablist" aria-label="Who is looking">
          {users.map(u => (
            <button key={u.id} role="tab" aria-selected={u.id === activeUser} aria-label={u.name}
                    className={`avatar ${u.id === activeUser ? 'active' : ''}`}
                    style={{ '--c': u.color } as React.CSSProperties}
                    onClick={() => onSelect(u.id)}>
              <span>{u.initials}</span>
            </button>
          ))}
        </div>
        {activeUser && <span className="topbar-name">{users.find(u => u.id === activeUser)?.name}</span>}
      </div>
      <div className="topbar-right">
        {sync && (
          <span className={`sync ${sync.stale ? 'stale' : ''}`} title={sync.last_error ?? ''}>
            {sync.stale ? <CloudOff size={18} /> : <RefreshCw size={16} />}
            {sync.stale ? `Last sync ${ago(sync.last_success)}` : `Synced ${ago(sync.last_success)}`}
          </span>
        )}
        <button className="btn icon-btn" onClick={() => nav('/accounts')} aria-label="Garmin accounts and settings">
          <UserCog size={24} />
        </button>
        <span className="clock num">{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      </div>
    </header>
  )
}
