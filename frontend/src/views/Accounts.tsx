import { AlertTriangle, Loader2, RefreshCw, UserPlus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'
import type { Account } from '../api'
import { ConnectForm } from '../components/ConnectForm'
import { ago } from '../format'
import './Detail.css'

const PHASE_LABEL: Record<string, string> = {
  logging_in: 'Logging in…', mfa_required: 'Waiting for security code', downloading: 'Downloading from Garmin…',
  importing: 'Analysing activities…',
}

export function Accounts() {
  const { reload } = useApp()
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(() => api.accounts().then(setAccounts).catch(e => setErr(String(e))), [])
  useEffect(() => { load() }, [load])
  // keep sync progress fresh while anything is running
  useEffect(() => {
    if (!accounts?.some(a => a.job)) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [accounts, load])

  const syncNow = async (id: string) => {
    setErr(null)
    try { await api.syncNow(id); await load() } catch (e) { setErr(String(e).replace(/^Error: /, '')) }
  }

  const connected = useCallback(() => { load(); reload() }, [load, reload])

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="muted">Settings</div>
          <h1>Garmin accounts</h1>
        </div>
      </div>
      {err && <div className="card tone-worse"><AlertTriangle size={18} /> {err}</div>}

      <div className="detail-grid">
        {accounts?.map(a => {
          const job = a.job
          return (
            <div key={a.id} className="card span-6">
              <div className="between">
                <div className="row" style={{ alignItems: 'center' }}>
                  <span className="avatar active" style={{ '--c': a.color, cursor: 'default' } as React.CSSProperties}><span>{a.initials}</span></span>
                  <div className="stack" style={{ gap: 0 }}>
                    <b style={{ fontSize: 22 }}>{a.name}</b>
                    <span className="muted" style={{ fontSize: 15 }}>{a.activities} activities</span>
                  </div>
                </div>
                <button className="btn" onClick={() => syncNow(a.id)} disabled={!!job}>
                  {job ? <Loader2 size={18} className="spin" /> : <RefreshCw size={18} />} {job ? 'Syncing' : 'Sync now'}
                </button>
              </div>
              <div style={{ marginTop: 12, fontSize: 16 }}>
                {job ? (
                  <>
                    <div>{PHASE_LABEL[job.phase] ?? job.message}</div>
                    {job.log.length > 0 && <code className="log" style={{ display: 'block', fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--faint)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{job.log[job.log.length - 1]}</code>}
                  </>
                ) : a.sync.last_error ? (
                  <span className="tone-warn"><AlertTriangle size={15} /> Last sync failed: {a.sync.last_error}</span>
                ) : (
                  <span className={a.sync.stale ? 'tone-warn' : 'muted'}>Last synced {ago(a.sync.last_success)}</span>
                )}
              </div>
              <div className="kv" style={{ marginTop: 14 }}>
                {([['max_hr', 'Max HR'], ['rest_hr', 'Resting HR'], ['ftp', 'FTP']] as const).map(([k, label]) => (
                  <div key={k}>
                    <div className="k">{label}</div>
                    <div className="v num" style={{ fontSize: 20 }}>{a.profile[k].value == null ? '—' : Math.round(Number(a.profile[k].value))}</div>
                  </div>
                ))}
              </div>
            </div>
          )
        })}

        <div className="card span-12">
          <div className="card-title"><UserPlus size={18} /> {accounts?.length ? 'Connect another Garmin account' : 'Connect your Garmin account'}</div>
          {adding || !accounts?.length
            ? <ConnectForm onDone={connected} />
            : <button className="btn" onClick={() => setAdding(true)}><UserPlus size={18} /> Add a person</button>}
        </div>
      </div>
    </div>
  )
}
