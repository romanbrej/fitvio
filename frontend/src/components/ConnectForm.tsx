import { AlertTriangle, Check, KeyRound, Loader2, LogIn, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Job } from '../api'
import './ConnectForm.css'

const JOB_KEY = 'healthwall.connectJob'
const store = {
  get: () => { try { return localStorage.getItem(JOB_KEY) } catch { return null } },
  set: (v: string | null) => { try { v ? localStorage.setItem(JOB_KEY, v) : localStorage.removeItem(JOB_KEY) } catch { /* private mode */ } },
}

const STEPS: { phase: Job['phase']; label: string }[] = [
  { phase: 'logging_in', label: 'Log in to Garmin Connect' },
  { phase: 'mfa_required', label: 'Security code' },
  { phase: 'downloading', label: 'Download your history' },
  { phase: 'importing', label: 'Analyse every activity' },
  { phase: 'done', label: 'Ready' },
]
const ORDER = STEPS.map(s => s.phase)

function elapsed(from: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(from).getTime()) / 1000))
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`
}

/** Connect a Garmin account: email + password (+ MFA code), then live progress of the first download. */
export function ConnectForm({ onDone, resume }: { onDone: () => void; resume?: Job | null }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [, tick] = useState(0)

  // Resume a running connect after a page reload.
  useEffect(() => {
    if (resume) { setJob(resume); return }
    const id = store.get()
    if (id) api.job(id).then(setJob).catch(() => store.set(null))
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
      const j = await api.connect(email.trim(), password)
      setPassword('')  // never keep it around in the page
      store.set(j.id)
      setJob(j)
    } catch (err) {
      setError(String(err).replace(/^Error: /, ''))
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
      setError(String(err).replace(/^Error: /, ''))
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
      store.set(j.id)
      setJob(j)
    } catch (err) {
      setError(String(err).replace(/^Error: /, ''))
    }
  }

  if (!job) {
    return (
      <form className="connect" onSubmit={submit}>
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
        {error && <div className="connect-error" role="alert"><AlertTriangle size={18} /> {error}</div>}
        <button className="btn btn-primary" type="submit" disabled={busy || !email || !password}>
          {busy ? <Loader2 size={20} className="spin" /> : <LogIn size={20} />} Connect Garmin
        </button>
        <p className="connect-note">
          <ShieldCheck size={16} /> Name, heart-rate zones, FTP and your whole history are read from Garmin — nothing else to fill in.
          The password is stored only on the dashboard server in your home network.
        </p>
      </form>
    )
  }

  const current = job.phase === 'error' ? -1 : ORDER.indexOf(job.phase)
  const showMfaStep = job.phase === 'mfa_required' || job.log.length > 0 || current >= 2
  return (
    <div className="connect">
      <ol className="steps">
        {STEPS.filter(s => s.phase !== 'mfa_required' || showMfaStep).map(s => {
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
