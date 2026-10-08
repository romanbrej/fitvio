import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from './api'
import { DEMO, DEMO_LOCKED } from './demo/demo'
import type { Ambient, AppConfig, Job, WallState } from './api'
import { DayScreen } from './components/DayScreen'
import { NightScreen } from './components/NightScreen'
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
const MORNING_FROM_HOUR = 4          // same as the server: a tap before this is still the night
const MORNING_RETRY_MS = 10 * 60_000 // someone's night is still missing: ask again on a tap after this
const DAY_SCREEN_IDLE_MS = 60_000    // a minute without a tap on the overview → the calm day screen
const PAUSE_IDLE_MS = 60_000         // someone else's avatar tapped during a verdict: the verdict returns after a minute without input

/** decodeURIComponent that survives a malformed URL (it throws on a stray "%") instead of crashing the app. */
function safeDecode(s: string): string {
  try { return decodeURIComponent(s) } catch { return s }
}

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
  const [serverWall, setWall] = useState<WallState | null>(null)
  // Another person tapped their avatar during a takeover: show them, without ending the verdict (it returns when idle).
  const [pause, setPause] = useState<{ user: string; session: string; ambient: Ambient } | null>(null)
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
    const es = DEMO ? null : new EventSource('/api/events')
    es?.addEventListener('refresh', () => refresh())
    return () => { clearInterval(poll); es?.close() }
  }, [refresh])

  // What this screen shows: the server's wall, or the paused-for person's overview.
  const paused = pause && serverWall?.mode === 'verdict' && serverWall.session.id === pause.session ? pause : null
  const wall = useMemo<WallState | null>(
    () => paused ? { mode: 'ambient', user_id: paused.user, ambient: paused.ambient } : serverWall, [paused, serverWall])

  // The pause ends after a minute without input, or once its verdict is over (or a newer one arrived).
  const pauseUser = paused?.user
  useEffect(() => {
    if (!pauseUser) return  // a stale pause (verdict over or replaced) is simply ignored above
    let timer = window.setTimeout(() => setPause(null), PAUSE_IDLE_MS)
    const reset = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => setPause(null), PAUSE_IDLE_MS)
    }
    const evs = ['pointerdown', 'keydown', 'scroll', 'wheel'] as const
    evs.forEach(e => window.addEventListener(e, reset, { passive: true }))
    return () => {
      window.clearTimeout(timer)
      evs.forEach(e => window.removeEventListener(e, reset))
    }
  }, [pauseUser])

  // Keep the paused-for person's overview as fresh as the wall.
  useEffect(() => {
    if (!pauseUser) return
    api.ambient(pauseUser).then(a => setPause(p => p && p.user === pauseUser ? { ...p, ambient: a } : p)).catch(() => {})
  }, [serverWall, pauseUser])

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

  // Day screen: after a minute without input on the overview (not during a post-workout takeover).
  const [dayScreen, setDayScreen] = useState(false)
  const wallMode = wall?.mode
  useEffect(() => {
    if (loc.pathname !== '/' || wallMode !== 'ambient') {
      setDayScreen(false)
      return
    }
    let timer = window.setTimeout(() => setDayScreen(true), DAY_SCREEN_IDLE_MS)
    const reset = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => setDayScreen(true), DAY_SCREEN_IDLE_MS)
    }
    const evs = ['pointerdown', 'keydown', 'wheel'] as const
    evs.forEach(e => window.addEventListener(e, reset, { passive: true }))
    return () => {
      window.clearTimeout(timer)
      evs.forEach(e => window.removeEventListener(e, reset))
    }
  }, [loc.pathname, wallMode])

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
    if (serverWall?.mode === 'verdict' && id !== serverWall.user_id) {
      // someone else during a takeover: show them for now; the verdict stays and comes back when idle
      const ambient = await api.ambient(id)
      setPause({ user: id, session: serverWall.session.id, ambient })
    } else {
      setPause(null)  // the verdict's own person (or no takeover): back to what the server shows
    }
    await refresh()
    if (loc.pathname !== '/') nav('/')
  }, [serverWall, refresh, loc.pathname, nav])

  // Show a running sync job in the top bar until it finishes, then refresh the wall.
  const follow = useCallback(async (job: Job) => {
    setSyncOutcome(null)
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
  }, [refresh])

  // Manual "sync now" for the person on screen: fetch the latest from Garmin, then refresh the wall.
  const syncNow = useCallback(async (user: string) => {
    if (syncJob) return
    let job: Job
    try {
      job = await api.syncNow(user)
    } catch (e) {
      setSyncOutcome({ ok: false, text: DEMO ? DEMO_LOCKED : `Sync failed: ${String(e).replace(/^Error: /, '')}` })
      return
    }
    await follow(job)
  }, [syncJob, follow])

  // The first tap of the morning fetches last night (sleep, HRV, Body Battery) right away instead of
  // waiting for the hourly sync. The server decides who needs it; here we only avoid asking on every tap.
  const morning = useRef({ day: '', next: 0 })
  const wallUser = wall?.mode === 'setup' ? null : wall?.user_id
  useEffect(() => {
    const onTap = () => {
      const now = new Date()
      const day = now.toDateString()
      const m = morning.current
      if (now.getHours() < MORNING_FROM_HOUR || (m.day === day && (m.next === 0 || Date.now() < m.next))) return
      morning.current = { day, next: Date.now() + MORNING_RETRY_MS }
      api.morning().then(r => {
        if (!r.pending) morning.current = { day, next: 0 }  // everyone's night is in: done for today
        const mine = r.started.find(j => j.user_id === wallUser)
        if (mine && !syncJob) follow(mine)
      }).catch(() => { morning.current = { day: '', next: 0 } })  // offline: try again on the next tap
    }
    window.addEventListener('pointerdown', onTap, { passive: true })
    return () => window.removeEventListener('pointerdown', onTap)
  }, [wallUser, syncJob, follow])

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
    ? safeDecode(loc.pathname.slice(9)).split(':')[0] : null)
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
      {dayScreen && !night && wall.mode === 'ambient' && loc.pathname === '/' && (
        <DayScreen ambient={wall.ambient} onWake={() => setDayScreen(false)} />
      )}
      {night && loc.pathname !== '/accounts' && wall.mode !== 'setup' && (
        <NightScreen ambient={wall.ambient} onWake={() => setWakeUntil(Date.now() + 120_000)} />
      )}
    </AppCtx.Provider>
  )
}
