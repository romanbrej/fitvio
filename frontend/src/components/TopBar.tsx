import { AlertTriangle, Check, ChevronLeft, CloudOff, RefreshCw, UserCog } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { Job, SyncInfo, User } from '../api'
import { ago } from '../format'
import './TopBar.css'

export type SyncOutcome = { ok: boolean; text: string } | null

function SyncButton({ sync, job, outcome, onSync, onFix }: {
  sync: SyncInfo; job: Job | null; outcome: SyncOutcome; onSync: () => void; onFix: () => void
}) {
  let icon = sync.stale ? <CloudOff size={18} /> : <RefreshCw size={18} />
  let text = sync.stale ? `Last sync ${ago(sync.last_success)}` : `Synced ${ago(sync.last_success)}`
  let tone = sync.stale ? 'stale' : ''
  let onClick = onSync
  if (sync.login_expired && !job) {
    // the auto-sync check stopped because the cached Garmin login expired — fix it in Accounts
    icon = <AlertTriangle size={18} />
    text = 'Garmin login expired — tap to fix'
    tone = 'stale'
    onClick = onFix
  }
  if (job) {
    icon = <RefreshCw size={18} className="spin" />
    text = job.phase === 'importing' ? 'Analysing…' : job.step ? `Syncing · ${job.step}` : 'Syncing…'
    tone = 'busy'
  } else if (outcome) {
    icon = outcome.ok ? <Check size={18} /> : <AlertTriangle size={18} />
    text = outcome.text
    tone = outcome.ok ? 'done' : 'failed'
  }
  return (
    <button className={`sync ${tone}`} onClick={onClick} disabled={!!job}
            title={job ? 'Fetching the latest data from Garmin' : sync.last_error ?? 'Tap to fetch the latest data from Garmin now'}
            aria-label={job ? 'Syncing with Garmin' : `${text}. Tap to sync now`}>
      {icon}
      <span className="sync-text">{text}</span>
    </button>
  )
}

export function TopBar({ users, activeUser, onSelect, sync, syncJob, syncOutcome, onSync }: {
  users: User[]; activeUser: string | null; onSelect: (id: string) => void; sync: SyncInfo | null
  syncJob: Job | null; syncOutcome: SyncOutcome; onSync: () => void
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
        {sync && activeUser && <SyncButton sync={sync} job={syncJob} outcome={syncOutcome} onSync={onSync}
                                                   onFix={() => nav('/accounts')} />}
        <button className="btn icon-btn" onClick={() => nav('/accounts')} aria-label="Garmin accounts and settings">
          <UserCog size={24} />
        </button>
        <span className="clock num">{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      </div>
    </header>
  )
}
