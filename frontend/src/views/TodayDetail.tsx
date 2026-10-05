import { Check, ChevronRight } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api'
import type { Ambient, PlannedWorkout } from '../api'
import { SportIcon, VerdictPill } from '../components/icons'
import { WorkoutShape } from '../components/WorkoutShape'
import { SPORT_LABEL } from '../format'
import { READINESS_LEVEL, feedbackText, minutes, phraseLabel, stepKindLabel, stepLength, stepLook, targetText } from '../mission'
import { useFetch } from '../useFetch'
import './Detail.css'

function dayLabel(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

/** Why today is (or isn't) a good day for it — from Garmin's readiness and the app's own numbers. */
function readyLines(a: Ambient): { ok: boolean; title: string; lines: string[] } {
  const r = a.readiness
  const form = a.form?.form
  const ss = a.sweet_spot
  const h = a.health_latest
  const lines: string[] = []
  if (r) lines.push(`Garmin readiness ${r.score} (${READINESS_LEVEL[r.level ?? ''] ?? r.level})${r.feedback ? ` — ${feedbackText(r.feedback)?.toLowerCase()}` : ''}`)
  if (form != null) lines.push(`Form ${form > 0 ? '+' : ''}${Math.round(form)} — ${form > 5 ? 'fresh' : form > -10 ? 'neutral' : form > -30 ? 'productive fatigue' : 'very tired'}`)
  if (h.hrv_last_night != null && h.hrv_baseline_low != null && h.hrv_baseline_high != null) {
    lines.push(`HRV ${h.hrv_last_night} ms — ${h.hrv_last_night < h.hrv_baseline_low ? 'below' : h.hrv_last_night > h.hrv_baseline_high ? 'above' : 'inside'} your normal range`)
  }
  if (ss) lines.push(`Weekly load ${ss.load} of a ${ss.low}–${ss.high} sweet spot`)
  const low = r ? r.level === 'LOW' || r.level === 'POOR' : form != null && form < -30
  return { ok: !low, title: low ? 'Take it easy' : 'Yes — go for it', lines }
}

function Content({ a }: { a: Ambient }) {
  const nav = useNavigate()
  const w: PlannedWorkout | null = a.today_workout
  const ss = a.sweet_spot
  const s = a.streak
  if (!w) {
    return (
      <div className="detail">
        <section className="card hero stripes">
          <div className="label">Today · from your Garmin plan</div>
          <h1 className="display hero-title" style={{ color: 'var(--volt)' }}>Nothing planned.</h1>
          <p className="hero-sub">No workout in your Garmin Connect calendar today.</p>
        </section>
        <Upcoming a={a} />
      </div>
    )
  }
  const ready = readyLines(a)
  const workSteps = w.steps.filter(x => x.kind === 'interval')
  const workSec = workSteps.reduce((t, x) => t + (x.duration_s ?? 0), 0)
  const after = ss && w.est_load != null && !w.done ? ss.load + w.est_load : null
  return (
    <div className="detail">
      <section className="card hero stripes">
        <div className="hero-grid">
          <div className="stack" style={{ gap: 8 }}>
            <div className="label row" style={{ gap: 8 }}>
              <SportIcon sport={w.sport} size={18} /> {dayLabel(w.day)} · today in your Garmin plan
            </div>
            <h1 className="display hero-title" style={{ color: 'var(--volt)' }}>{w.title}{w.est_duration_s ? ` · ${minutes(w.est_duration_s)}` : ''}</h1>
            {w.description && <div className="hero-sub">“{w.description}”</div>}
            <div className="row" style={{ gap: 8 }}>
              {w.done
                ? <span className="pill tone-better"><Check size={15} /> Done{w.done.linked ? ' · started from the workout' : ''}</span>
                : <span className="tag garmin"><Check size={14} /> On your watch · synced from Garmin Connect</span>}
              {w.plan && <span className="chip">{w.plan.name}{w.plan.week && w.plan.weeks ? ` · week ${w.plan.week} of ${w.plan.weeks}` : ''}</span>}
            </div>
          </div>
          <div className="kpi-grid">
            <div className="tile"><div className="label">Duration</div><div className="v">{minutes(w.est_duration_s)}</div></div>
            <div className="tile"><div className="label">Type</div><div className="v" style={{ fontFamily: 'var(--display)', fontWeight: 800, fontSize: 24, textTransform: 'uppercase' }}>{phraseLabel(w.phrase) ?? SPORT_LABEL[w.sport]}</div></div>
            <div className="tile"><div className="label">Load (TRIMP)</div><div className="v">{w.est_load != null ? `~${w.est_load}` : '—'}</div></div>
            <div className="tile"><div className="label">Hard part</div><div className="v">{workSec ? minutes(workSec) : workSteps.length ? `${workSteps.length} blocks` : '—'}</div></div>
          </div>
        </div>
      </section>

      {w.done && (
        <button className="card done-card" onClick={() => nav(`/session/${encodeURIComponent(w.done!.session_id)}`)}>
          <span className="done-check"><Check size={22} strokeWidth={3} /></span>
          <div className="stack" style={{ gap: 2, minWidth: 0 }}>
            <div className="display" style={{ fontSize: 30 }}>Done · {w.done.name ?? w.title}</div>
            <div className="muted">{w.done.targets ? `${w.done.targets.hit} of ${w.done.targets.of} work blocks in the target pace · ` : ''}{w.done.headline}</div>
          </div>
          <span className="grow" />
          {w.done.verdict && <VerdictPill verdict={w.done.verdict} />}
          <span className="link">Session <ChevronRight size={16} /></span>
        </button>
      )}

      {w.steps.length > 0 && (
        <section className="card">
          <div className="card-title">Workout profile</div>
          <WorkoutShape steps={w.steps} height={190} labels={x => x.kind === 'interval' ? targetText(x) : null} />
          <div className="wshape-axis num">
            {w.steps.map((x, i) => <span key={i} style={{ flexGrow: x.duration_s ?? 60 }}>{stepLength(x)}</span>)}
          </div>
        </section>
      )}

      {w.steps.length > 0 && (
        <section className="card">
          <div className="card-title">Step by step</div>
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>#</th><th>Step</th><th className="num">Length</th><th className="num">Target</th></tr></thead>
              <tbody>
                {w.steps.map((x, i) => (
                  <tr key={i}>
                    <td className="num faint">{i + 1}</td>
                    <td><span className="step-name"><i style={{ background: stepLook(x).color }} />{stepKindLabel(x.kind)}</span>{x.description ? <span className="muted"> · {x.description}</span> : null}</td>
                    <td className="num">{stepLength(x)}</td>
                    <td className="num" style={{ color: x.kind === 'interval' ? 'var(--volt)' : undefined }}>{targetText(x) ?? 'easy'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {!w.done && <div className="detail-grid">
        {(
          <section className="card span-5">
            <div className="card-title">Are you ready for it?</div>
            <div className="display" style={{ fontSize: 40, color: ready.ok ? 'var(--better)' : 'var(--warn)', marginBottom: 8 }}>{ready.title}</div>
            <ul className="reasons-list">{ready.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
          </section>
        )}
        <section className="card span-7">
          <div className="card-title">What it does for you</div>
          <div className="impact-grid">
            {after != null && ss && (
              <div className="tile">
                <div className="label">Weekly load</div>
                <div className="impact"><span className="from num">{ss.load}</span> → <span className="num to" style={{ color: 'var(--volt)' }}>{after}</span></div>
                <div className="small strong" style={{ color: after > ss.high ? 'var(--accent-2)' : after >= ss.low ? 'var(--volt)' : 'var(--muted)' }}>
                  {after > ss.high ? 'Above the sweet spot' : after >= ss.low ? 'In the sweet spot ✓' : `${ss.low - after} short of the sweet spot`}</div>
              </div>
            )}
            {!w.done && (
              <div className="tile">
                <div className="label">Week streak</div>
                <div className="impact"><span className="from num">{s.this_week}/{s.min_sessions}</span> → <span className="num to" style={{ color: 'var(--accent-2)' }}>{Math.min(s.this_week + 1, s.min_sessions)}/{s.min_sessions}</span></div>
                <div className="small strong" style={{ color: 'var(--accent-2)' }}>{s.this_week + 1 >= s.min_sessions ? `${s.weeks + (s.needed > 0 ? 1 : 0)}-week streak ${s.needed > 0 ? 'secured' : 'kept'}` : `${s.needed - 1} more after this`}</div>
              </div>
            )}
            {a.form && w.est_load != null && !w.done && (
              <div className="tile">
                <div className="label">Form tomorrow</div>
                <div className="impact"><span className="from num">{Math.round(a.form.form)}</span> → <span className="num to" style={{ color: 'var(--form)' }}>{Math.round(formAfter(a, w.est_load))}</span></div>
                <div className="small muted">roughly, after this workout</div>
              </div>
            )}
          </div>
        </section>
      </div>}

      <Upcoming a={a} />
    </div>
  )
}

/** Form tomorrow morning if today's workout is done: one day of CTL/ATL decay with today's load. */
function formAfter(a: Ambient, load: number): number {
  const f = a.form!
  const kc = 1 - Math.exp(-1 / 42), ka = 1 - Math.exp(-1 / 7)
  const todayLoad = (a.pmc.at(-1)?.load ?? 0) + load
  // today's row already holds today's training so far: redo today with the planned load, then one rest day
  const prev = a.pmc.at(-2) ?? f
  let ctl = prev.fitness + (todayLoad - prev.fitness) * kc
  let atl = prev.fatigue + (todayLoad - prev.fatigue) * ka
  ctl -= ctl * kc
  atl -= atl * ka
  return ctl - atl
}

function Upcoming({ a }: { a: Ambient }) {
  if (!a.upcoming.length) return null
  return (
    <section className="stack" style={{ gap: 10 }}>
      <div className="card-title" style={{ margin: 0 }}>Coming up in your Garmin plan</div>
      <div className="upcoming">
        {a.upcoming.slice(0, 4).map(u => (
          <div key={u.day} className="card up-card">
            <div className="label" style={{ color: 'var(--run)' }}>{dayLabel(u.day)}</div>
            <div className="display" style={{ fontSize: 28, fontWeight: 800 }}>{u.title}</div>
            <div className="muted small">{[phraseLabel(u.phrase), u.description].filter(Boolean).join(' · ')}</div>
            <div className="num small" style={{ color: 'var(--text-2)', marginTop: 4 }}>
              {[u.est_duration_s ? minutes(u.est_duration_s) : null, u.est_load != null ? `load ~${u.est_load}` : null].filter(Boolean).join(' · ')}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

export function TodayDetail() {
  const { user } = useParams()
  const { wall } = useApp()
  const own = wall && wall.mode !== 'setup' && wall.user_id === user ? wall.ambient : null
  const { data } = useFetch(() => own ? Promise.resolve(own) : api.ambient(user!), [user, own])
  const a = own ?? data
  if (!a) return <div className="muted">Loading…</div>
  return <Content a={a} />
}
