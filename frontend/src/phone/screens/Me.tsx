import { AlertTriangle, Loader2, Plus, RefreshCw, Wifi } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api'
import type { Account, ActivityCheck, BuddySettings } from '../../api'
import { ANIMALS, Buddy } from '../../components/Buddy'
import type { Animal } from '../../components/Buddy'
import { HrSettings } from '../../components/HrSettings'
import { ago } from '../../format'
import { usePhone } from '../ctx'
import { Avatar, Card } from '../parts'

const errorText = (e: unknown) => String(e).replace(/^Error: /, '')

/** Who uses this phone, their heart-rate values, their buddy, the accounts and auto-sync. */
export function Me() {
  const { config, me, setMe, refresh } = usePhone()
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [buddies, setBuddies] = useState<BuddySettings | null>(null)
  const [check, setCheck] = useState<ActivityCheck | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  const load = useCallback(() => api.accounts().then(setAccounts).catch(e => setProblem(errorText(e))), [])
  useEffect(() => { load() }, [load])
  useEffect(() => { api.buddySettings().then(setBuddies).catch(() => setBuddies(null)) }, [])
  useEffect(() => { api.activityCheck().then(setCheck).catch(() => setCheck(null)) }, [])
  useEffect(() => {
    // keep sync progress fresh while anything runs
    if (!accounts?.some(a => a.job)) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [accounts, load])

  const syncNow = async (id: string) => {
    setProblem(null)
    try { await api.syncNow(id); await load() } catch (e) { setProblem(errorText(e)) }
  }
  const pickBuddy = async (animal: Animal) => {
    setProblem(null)
    try { setBuddies(await api.setBuddy(me.id, animal)); refresh() } catch (e) { setProblem(errorText(e)) }
  }
  const toggleCheck = async () => {
    if (!check) return
    setProblem(null)
    try { setCheck(await api.setActivityCheck(!check.enabled)) } catch (e) { setProblem(errorText(e)) }
  }
  const mine = buddies?.users[me.id]
  const myAccount = accounts?.find(a => a.id === me.id)

  return (
    <div className="ph-stack">
      <header className="ph-row" style={{ gap: 14 }}>
        <Avatar user={me} size="lg" />
        <div className="ph-grow"><h1 className="ph-title">{me.name}</h1><span className="ph-foot">This phone shows {me.name}</span></div>
      </header>
      {problem && <Card className="tone-worse"><span><AlertTriangle size={16} aria-hidden /> {problem}</span></Card>}

      {config.users.length > 1 && (
        <Card>
          <span className="ph-label">Who uses this phone?</span>
          <div className="ph-row" role="radiogroup" aria-label="Person on this phone" style={{ gap: 12, flexWrap: 'wrap' }}>
            {config.users.map(u => (
              <button key={u.id} role="radio" aria-checked={u.id === me.id} className={`ph-who${u.id === me.id ? ' on' : ''}`}
                      onClick={() => setMe(u.id)}>
                <Avatar user={u} size="lg" /><span>{u.name}</span>
              </button>
            ))}
          </div>
          <span className="ph-caption">Remembered on this phone only. Switching here never changes the wall.</span>
        </Card>
      )}

      {myAccount && (
        <Card>
          <span className="ph-label">Heart rate</span>
          <HrSettings account={myAccount} onSaved={load} />
        </Card>
      )}

      {buddies && (
        <Card>
          <div className="ph-row" style={{ gap: 12 }}>
            {mine && <Buddy animal={mine} mood="happy" size={56} />}
            <div className="ph-grow"><span className="ph-label">Training buddy</span><span className="ph-strong" style={{ textTransform: 'capitalize' }}>{mine ?? '—'}</span></div>
          </div>
          <div className="ph-buddies" role="radiogroup" aria-label="Buddy animal">
            {ANIMALS.map(an => (
              <button key={an} role="radio" aria-checked={mine === an} className={mine === an ? 'on' : ''}
                      onClick={() => pickBuddy(an)} aria-label={`${an}, eats ${buddies.food[an]}`}>
                <Buddy animal={an} mood="happy" size={36} /><span>{an}</span>
              </button>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <span className="ph-label">Accounts</span>
        {accounts?.map(a => (
          <div key={a.id} className="ph-list-row">
            <Avatar user={a} size="sm" />
            <div className="ph-grow">
              <span className="ph-strong">{a.name}</span>
              {a.job ? <span className="ph-foot">Syncing…</span>
                : a.sync.login_expired ? <span className="ph-foot tone-warn">Garmin login expired — Sync logs in again</span>
                : a.sync.last_error ? <span className="ph-foot tone-warn">Last sync failed{a.source === 'intervals' && /API key/.test(a.sync.last_error) ? ' — check the API key' : ''}</span>
                : <span className={`ph-foot ${a.sync.stale ? 'tone-warn' : 'tone-better'}`}>Synced {ago(a.sync.last_success)}</span>}
            </div>
            <button className={`ph-btn sm${a.sync.login_expired ? ' warn' : ''}`} onClick={() => syncNow(a.id)} disabled={!!a.job}
                    aria-label={`Sync ${a.name} now`}>
              {a.job ? <Loader2 size={16} className="spin" aria-hidden /> : <RefreshCw size={16} aria-hidden />}{a.sync.login_expired ? 'Fix' : 'Sync'}
            </button>
          </div>
        ))}
        {check && (
          <div className="ph-list-row">
            <div className="ph-grow">
              <span className="ph-strong">Auto-sync on new activity</span>
              <span className="ph-foot">{check.backoff_until ? `Paused until ${check.backoff_until.slice(11, 16)} (Garmin rate limit)`
                : `Checks for new activities every ${Math.round(check.interval_s / 60)}–10 min, ${check.active_hours}`}</span>
            </div>
            <button role="switch" aria-checked={check.enabled} className={`switch ${check.enabled ? 'on' : ''}`}
                    onClick={toggleCheck} aria-label="Auto-sync on new activity"><span /></button>
          </div>
        )}
        <Link to="/me/connect" className="ph-list-row ph-add"><Plus size={22} aria-hidden />Add a person</Link>
      </Card>

      <p className="ph-note"><Wifi size={18} aria-hidden />Fitvio runs on your home server and only works on your home Wi-Fi. Your logins and health data never leave your house.</p>
    </div>
  )
}
