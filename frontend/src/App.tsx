import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from './api'
import type { AppConfig, Job, WallState } from './api'
import { TopBar } from './components/TopBar'
import type { SyncOutcome } from './components/TopBar'
import './App.css'

interface Ctx {
  config: AppConfig
  wall: WallState | null
  userId: string | null
  refresh: () => Promise<void>
  reload: () => void
  select: (id: string) => Promise<void>
  dismiss: (sessionId: string) => Promise<void>
}

const AppCtx = createContext<Ctx | null>(null)
export const useApp = () => useContext(AppCtx)!

const POLL_MS = 60_000
const JOB_POLL_MS = 1500
const OUTCOME_MS = { ok: 6_000, failed: 15_000 }

function inNight(start: string, end: string, d = new Date()): boolean {
  const m = d.getHours() * 60 + d.getMinutes()
  const [sh, sm] = start.split(':').map(Number)
  const [eh, em] = end.split(':').map(Number)
  const s = sh * 60 + sm
  const e = eh * 60 + em
  return s > e ? m >= s || m < e : m >= s && m < e
}

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [wall, setWall] = useState<WallState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [night, setNight] = useState(false)
  const [wakeUntil, setWakeUntil] = useState(0)
  const nav = useNavigate()
  const loc = useLocation()
  const idleTimer = useRef<number | undefined>(undefined)
  const [syncJob, setSyncJob] = useState<Job | null>(null)
  const [syncOutcome, setSyncOutcome] = useState<SyncOutcome>(null)

  const refresh = useCallback(async () => {
    try {
      setWall(await api.wall())
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }, [])

  const reload = useCallback(() => {
    api.config().then(setConfig).catch(e => setError(String(e)))
    refresh()
  }, [refresh])

  useEffect(() => {
    api.config().then(setConfig).catch(e => setError(String(e)))
    refresh()
    const poll = setInterval(refresh, POLL_MS)
    // Server-sent events: the backend pushes 'refresh' as soon as a new verdict lands.
    const es = new EventSource('/api/events')
    es.addEventListener('refresh', () => refresh())
    return () => { clearInterval(poll); es.close() }
  }, [refresh])

  // A fresh verdict pulls the wall back to the front even from a detail page.
  const prevMode = useRef<string | null>(null)
  useEffect(() => {
    const key = wall?.mode === 'verdict' ? `v:${wall.session.id}` : wall?.mode ?? null
    if (key?.startsWith('v:') && key !== prevMode.current && loc.pathname !== '/' && loc.pathname !== '/accounts') nav('/')
    prevMode.current = key
  }, [wall, loc.pathname, nav])

  // Idle → back to the wall.
  useEffect(() => {
    if (!config) return
    const reset = () => {
      window.clearTimeout(idleTimer.current)
      if (loc.pathname !== '/' && loc.pathname !== '/accounts') {
        idleTimer.current = window.setTimeout(() => nav('/'), config.wall.idle_return_seconds * 1000)
      }
    }
    reset()
    const evs = ['pointerdown', 'keydown', 'scroll', 'wheel'] as const
    evs.forEach(e => window.addEventListener(e, reset, { passive: true }))
    return () => {
      window.clearTimeout(idleTimer.current)
      evs.forEach(e => window.removeEventListener(e, reset))
    }
  }, [config, loc.pathname, nav])

  // Night dimming (tap wakes it for 2 minutes).
  useEffect(() => {
    if (!config) return
    const tick = () => setNight(inNight(config.wall.night_start, config.wall.night_end) && Date.now() > wakeUntil)
    tick()
    const t = setInterval(tick, 30_000)
    return () => clearInterval(t)
  }, [config, wakeUntil])

  const select = useCallback(async (id: string) => {
    await api.select(id)
    await refresh()
    if (loc.pathname !== '/') nav('/')
  }, [refresh, loc.pathname, nav])

  // Manual "sync now" for the person on screen: fetch the latest from Garmin, then refresh the wall.
  const syncNow = useCallback(async (user: string) => {
    if (syncJob) return
    setSyncOutcome(null)
    let job: Job
    try {
      job = await api.syncNow(user)
    } catch (e) {
      setSyncOutcome({ ok: false, text: `Sync failed: ${String(e).replace(/^Error: /, '')}` })
      return
    }
    setSyncJob(job)
    while (job.phase !== 'done' && job.phase !== 'error') {
      await new Promise(r => setTimeout(r, JOB_POLL_MS))
      try {
        job = await api.job(job.id)
        setSyncJob(job)
      } catch {
        // server restarting or connection blip: keep polling
      }
    }
    setSyncJob(null)
    const ok = job.phase === 'done'
    setSyncOutcome({ ok, text: ok ? job.message || 'Up to date' : (job.error ?? 'Sync failed') })
    await refresh()
  }, [syncJob, refresh])

  useEffect(() => {
    if (!syncOutcome) return
    const t = setTimeout(() => setSyncOutcome(null), syncOutcome.ok ? OUTCOME_MS.ok : OUTCOME_MS.failed)
    return () => clearTimeout(t)
  }, [syncOutcome])

  const dismiss = useCallback(async (sid: string) => {
    await api.dismiss(sid)
    await refresh()
  }, [refresh])

  if (!config || !wall) {
    return <div className="boot">{error ? <><b>Can't reach the dashboard server.</b><span className="muted">{error}</span></> : 'Loading…'}</div>
  }
  // Detail pages belong to the person in the URL (/u/:user/…); the wall to its current person.
  const routeUser = loc.pathname.match(/^\/u\/([^/]+)/)?.[1] ?? (loc.pathname.startsWith('/session/')
    ? decodeURIComponent(loc.pathname.slice(9)).split(':')[0] : null)
  const userId = routeUser ?? (wall.mode === 'setup' ? null : wall.user_id)
  // the sync status we have is the wall person's; don't show it on another person's detail page
  const sync = wall.mode !== 'setup' && wall.user_id === userId ? wall.ambient.sync : null

  return (
    <AppCtx.Provider value={{ config, wall, userId, refresh, reload, select, dismiss }}>
      <div className="shell">
        <TopBar users={config.users} activeUser={userId} onSelect={select} sync={sync}
                syncJob={syncJob} syncOutcome={syncOutcome} onSync={() => userId && syncNow(userId)} />
        <main className="main"><Outlet /></main>
        {error && <div className="offline" role="status">Connection lost — showing last data</div>}
      </div>
      {night && loc.pathname !== '/accounts' && wall.mode !== 'setup' && <button className="night" aria-label="Wake display" onClick={() => setWakeUntil(Date.now() + 120_000)} />}
    </AppCtx.Provider>
  )
}
