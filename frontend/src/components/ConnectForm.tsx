import { AlertTriangle, Check, KeyRound, Loader2, Lock, LogIn, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { DEMO, DEMO_LOCKED } from '../demo/demo'
import type { Job, Source } from '../api'
import './ConnectForm.css'

const JOB_KEY = 'fitvio.connectJob'
/** The running connect job, as "<source>:<job id>" (older pages stored the bare id: Garmin). */
const store = {
  get: (): { source: Source; id: string } | null => {
    try {
      const v = localStorage.getItem(JOB_KEY)
      if (!v) return null
      const [source, id] = v.includes(':') ? v.split(':', 2) : ['garmin', v]
      return { source: source === 'intervals' ? 'intervals' : 'garmin', id }
    } catch { return null }
  },
  set: (v: { source: Source; id: string } | null) => {
    try {
      if (v) localStorage.setItem(JOB_KEY, `${v.source}:${v.id}`)
      else localStorage.removeItem(JOB_KEY)
    } catch { /* private mode */ }
  },
}

const steps = (source: Source): { phase: Job['phase']; label: string }[] => [
  { phase: 'logging_in', label: source === 'intervals' ? 'Check your Intervals.icu key' : 'Log in to Garmin Connect' },
  { phase: 'mfa_required', label: 'Security code' },
  { phase: 'downloading', label: 'Download your history' },
  { phase: 'importing', label: 'Analyse every activity' },
  { phase: 'done', label: 'Ready' },
]
const ORDER = steps('garmin').map(s => s.phase)
const errorText = (e: unknown) => String(e).replace(/^Error: /, '')

function elapsed(from: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(from).getTime()) / 1000))
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`
}

/** Connect a Garmin account (email + password + MFA code) or an Intervals.icu account (athlete id +
 *  API key), then live progress of the first download. */
export function ConnectForm({ onDone, resume }: { onDone: () => void; resume?: Job | null }) {
  const [source, setSource] = useState<Source>('garmin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [athlete, setAthlete] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [code, setCode] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [, tick] = useState(0)

  // Resume a running connect after a page reload.
  useEffect(() => {
    if (resume) { setJob(resume); return }
    const saved = store.get()
    if (saved) {
      setSource(saved.source)
      api.job(saved.id).then(setJob).catch(() => store.set(null))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!job || job.phase === 'done' || job.phase === 'error') return
    const t = setInterval(() => {
      api.job(job.id).then(j => {
        setJob(j)
        if (j.phase === 'done') { store.set(null); onDone() }
        if (j.phase === 'error') store.set(null)
      }).catch(() => { /* server restarting; keep polling */ })
      tick(n => n + 1)
    }, 1500)
    return () => clearInterval(t)
  }, [job, onDone])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const j = source === 'intervals'
        ? await api.connectIntervals(athlete.trim(), apiKey.trim())
        : await api.connect(email.trim(), password)
      setPassword(''); setApiKey('')  // never keep secrets around in the page
      store.set({ source, id: j.id })
      setJob(j)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const sendCode = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!job) return
    setBusy(true); setError(null)
    try {
      await api.mfa(job.id, code)
      setCode('')
      setJob({ ...job, phase: 'logging_in', message: 'Checking the code' })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const reset = () => { setJob(null); setError(null); store.set(null) }
  // Login worked but the download failed: the account is connected, so retry the download only.
  const retryDownload = async () => {
    if (!job?.user_id) return
    setError(null)
    try {
      const j = await api.syncNow(job.user_id)
      store.set({ source, id: j.id })
      setJob(j)
    } catch (err) {
      setError(errorText(err))
    }
  }

  if (!job) {
    const ready = source === 'intervals' ? athlete && apiKey : email && password
    return (
      <form className="connect" onSubmit={submit}>
        {DEMO && <p className="connect-note demo-locked" role="note"><Lock size={16} aria-hidden /> {DEMO_LOCKED}</p>}
        <fieldset disabled={DEMO} style={{ display: 'contents' }}>
        <div className="connect-source" role="radiogroup" aria-label="Where your data comes from">
          {(['garmin', 'intervals'] as const).map(s => (
            <button key={s} type="button" role="radio" aria-checked={source === s} className={source === s ? 'on' : ''}
                    onClick={() => { setSource(s); setError(null) }}>
              {s === 'garmin' ? 'Garmin' : 'Intervals.icu'}
            </button>
          ))}
        </div>
        {source === 'garmin' ? <>
          <label>
            <span>Garmin email</span>
            <input type="email" autoComplete="username" inputMode="email" required value={email}
                   onChange={e => setEmail(e.target.value)} placeholder="you@example.com" />
          </label>
          <label>
            <span>Garmin password</span>
            <input type="password" autoComplete="current-password" required value={password}
                   onChange={e => setPassword(e.target.value)} />
          </label>
        </> : <>
          <label>
            <span>Athlete ID</span>
            <input autoComplete="off" autoCapitalize="none" spellCheck={false} required value={athlete}
                   onChange={e => setAthlete(e.target.value)} placeholder="i123456" />
          </label>
          <label>
            <span>API key</span>
            <input type="password" autoComplete="off" required value={apiKey} onChange={e => setApiKey(e.target.value)} />
          </label>
        </>}
        {error && <div className="connect-error" role="alert"><AlertTriangle size={18} /> {error}</div>}
        <button className="btn btn-primary" type="submit" disabled={DEMO || busy || !ready}>
          {busy ? <Loader2 size={20} className="spin" /> : <LogIn size={20} />} {source === 'garmin' ? 'Connect Garmin' : 'Connect Intervals.icu'}
        </button>
        {source === 'garmin' ? (
          <p className="connect-note">
            <ShieldCheck size={16} /> Name, heart-rate zones, FTP and your whole history are read from Garmin — nothing else to fill in.
            The password is stored only on the dashboard server in your home network.
          </p>
        ) : <>
          <p className="connect-note">
            <KeyRound size={16} /><span>Both are in Intervals.icu under <b>Settings → Developer settings</b>. Works with any watch that
            syncs to Intervals.icu: Garmin, Polar, Coros, Suunto, Wahoo — Apple Watch through the HealthFit app, Fitbit through Health Sync.</span>
          </p>
          <p className="connect-note">
            <ShieldCheck size={16} /> The key is stored only on the dashboard server in your home network. Activities that reach
            Intervals.icu only through Strava can't be read (Strava doesn't allow it).
          </p>
        </>}
        </fieldset>
      </form>
    )
  }

  const current = job.phase === 'error' ? -1 : ORDER.indexOf(job.phase)
  const showMfaStep = job.phase === 'mfa_required' || job.log.length > 0 || current >= 2
  return (
    <div className="connect">
      <ol className="steps">
        {steps(source).filter(s => s.phase !== 'mfa_required' || showMfaStep).map(s => {
          const i = ORDER.indexOf(s.phase)
          const state = job.phase === 'error' ? 'todo' : i < current || job.phase === 'done' ? 'done' : i === current ? 'now' : 'todo'
          return (
            <li key={s.phase} className={`step ${state}`}>
              <span className="step-icon">
                {state === 'done' ? <Check size={18} /> : state === 'now' ? <Loader2 size={18} className="spin" /> : null}
              </span>
              {s.label}
            </li>
          )
        })}
      </ol>

      {job.phase === 'mfa_required' && (
        <form className="mfa" onSubmit={sendCode}>
          <label>
            <span><KeyRound size={16} /> Security code from Garmin (email or authenticator app)</span>
            <input autoFocus inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]*" maxLength={8}
                   required value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))} />
          </label>
          <button className="btn btn-primary" type="submit" disabled={busy || code.length < 4}>Confirm code</button>
        </form>
      )}

      {job.phase !== 'error' && job.phase !== 'done' && (
        <div className="progress">
          <div>{job.message}</div>
          {job.step && job.step_index != null && job.step_total && (
            <div className="substep">
              <div className="substep-head">
                <b>Step {job.step_index + 1} of {job.step_total}</b> · {job.step}
              </div>
              <div className="substep-bar" aria-hidden><i style={{ width: `${(job.step_index / job.step_total) * 100}%` }} /></div>
              <div className="muted">Each step goes through your whole history, so its own progress below restarts at 0 %.</div>
            </div>
          )}
          <div className="muted">Running for {elapsed(job.started_at)}{job.phase === 'downloading' ? ' — you can leave this page, it continues in the background' : ''}</div>
          {job.log.length > 0 && <code className="log">{job.log[job.log.length - 1]}</code>}
        </div>
      )}

      {job.phase === 'done' && (
        <div className="connect-done">
          <Check size={22} /> Connected{job.name ? ` as ${job.name}` : ''} — {job.message}.
        </div>
      )}

      {(job.phase === 'error' || error) && (
        <>
          <div className="connect-error" role="alert"><AlertTriangle size={18} /> {job.error ?? error}</div>
          {job.user_id
            ? <button className="btn" onClick={retryDownload}>Retry download</button>
            : <button className="btn" onClick={reset}>Try again</button>}
        </>
      )}
    </div>
  )
}
