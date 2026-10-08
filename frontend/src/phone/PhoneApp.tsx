import { CalendarDays, TrendingUp, User as UserIcon, Zap } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, Outlet, ScrollRestoration, useLocation } from 'react-router-dom'
import { api } from '../api'
import { DEMO } from '../demo/demo'
import type { Ambient, AppConfig, Job } from '../api'
import { ConnectForm } from '../components/ConnectForm'
import { meStore, PhoneContext } from './ctx'
import { Offline } from './screens/Offline'
import { Picker } from './screens/Picker'
import './phone.css'

const POLL_MS = 60_000
const JOB_POLL_MS = 1500
/** About 30 s of failed status checks: the job is gone (e.g. the server restarted), stop showing "Syncing". */
const JOB_MAX_MISSES = 20

const TABS = [
  { to: '/', label: 'Today', Icon: Zap, match: (p: string) => p === '/' || p.startsWith('/verdict') || p.startsWith('/session') },
  { to: '/plan', label: 'Plan', Icon: CalendarDays, match: (p: string) => p.startsWith('/plan') },
  { to: '/trends', label: 'Trends', Icon: TrendingUp, match: (p: string) => p.startsWith('/trends') },
  { to: '/me', label: 'Me', Icon: UserIcon, match: (p: string) => p.startsWith('/me') },
]

function TabBar() {
  const { pathname } = useLocation()
  return (
    <nav className="ph-tabs" aria-label="Main">
      {TABS.map(({ to, label, Icon, match }) => {
        const on = match(pathname)
        return (
          <Link key={to} to={to} className={`ph-tab${on ? ' on' : ''}`} aria-current={on ? 'page' : undefined}>
            <Icon size={24} strokeWidth={2} aria-hidden />{label}
          </Link>
        )
      })}
    </nav>
  )
}

/** The phone app: one person (picked once on this phone), four tabs. It reads that person's data and never
 *  touches the wall — no /api/wall (that would count as the verdict being shown), no select, no dismiss. */
export function PhoneApp() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [configError, setConfigError] = useState(false)
  const [meId, setMeId] = useState<string | null>(meStore.get())
  const [fetched, setFetched] = useState<Ambient | null>(null)
  const [stale, setStale] = useState(false)
  const [syncJob, setSyncJob] = useState<Job | null>(null)

  const reloadConfig = useCallback(() => {
    api.config().then(c => { setConfig(c); setConfigError(false) }).catch(() => setConfigError(true))
  }, [])
  useEffect(reloadConfig, [reloadConfig])

  const me = config?.users.find(u => u.id === meId) ?? null
  const myId = me?.id

  const refresh = useCallback(async () => {
    if (!myId) return
    try {
      const a = await api.ambient(myId)
      setFetched(a)
      setStale(false)
    } catch {
      setStale(true)
    }
  }, [myId])

  // after switching person, the old person's data is never shown
  const ambient = fetched?.user_id === myId ? fetched : null

  useEffect(() => {
    if (!myId) return
    refresh()
    const poll = setInterval(refresh, POLL_MS)
    const es = DEMO ? null : new EventSource('/api/events')  // a new verdict lands → refresh right away
    es?.addEventListener('refresh', () => refresh())
    // a phone sleeps a lot: catch up when it comes back
    const onVisible = () => { if (document.visibilityState === 'visible') refresh() }
    document.addEventListener('visibilitychange', onVisible)
    return () => { clearInterval(poll); es?.close(); document.removeEventListener('visibilitychange', onVisible) }
  }, [myId, refresh])

  const setMe = useCallback((id: string | null) => {
    meStore.set(id)
    setMeId(id)
  }, [])

  const syncNow = useCallback(async () => {
    if (!myId || syncJob) return
    try {
      let job = await api.syncNow(myId)
      setSyncJob(job)
      let misses = 0
      while (job.phase !== 'done' && job.phase !== 'error' && misses < JOB_MAX_MISSES) {
        await new Promise(r => setTimeout(r, JOB_POLL_MS))
        try { job = await api.job(job.id); setSyncJob(job); misses = 0 } catch { misses++ }
      }
    } catch { /* already syncing or not allowed: the next poll shows the state */ }
    setSyncJob(null)
    await refresh()
  }, [myId, syncJob, refresh])

  if (!config) {
    return configError ? <Offline onRetry={reloadConfig} /> : <div className="ph-boot">Loading…</div>
  }
  if (!config.users.length) {
    return (
      <div className="ph ph-page ph-solo">
        <h1 className="ph-title">Welcome to Fitvio</h1>
        <p className="ph-sub">Connect your Garmin or Intervals.icu account. Your history is downloaded and every activity gets a verdict.</p>
        <ConnectForm onDone={reloadConfig} />
      </div>
    )
  }
  if (!me) return <Picker users={config.users} onPick={setMe} />
  if (!ambient && stale) return <Offline onRetry={refresh} />

  return (
    <PhoneContext.Provider value={{ config, me, ambient, stale, syncJob, syncNow, refresh, reloadConfig, setMe }}>
      <div className="ph">
        <main className="ph-page">
          {ambient ? <Outlet /> : <div className="ph-boot">Loading…</div>}
        </main>
        {stale && <div className="ph-stale" role="status">Server not reachable — showing the last data</div>}
        <TabBar />
      </div>
      <ScrollRestoration />
    </PhoneContext.Provider>
  )
}
