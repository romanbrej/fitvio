import { Check, ChevronRight } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api'
import type { Ambient, PlanDay, PlanWeek, PlannedWorkout } from '../api'
import { SportIcon, VerdictPill } from '../components/icons'
import { StatusMark, shortDuration } from '../components/WeekStrip'
import { WorkoutShape } from '../components/WorkoutShape'
import { SPORT_LABEL } from '../format'
import { READINESS_LEVEL, isEasy, feedbackText, minutes, phraseLabel, stepKindLabel, stepLength, stepLook, targetText } from '../mission'
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

const STATUS_LINE: Record<string, string> = { missed: 'Missed', today: 'Today', planned: 'Planned', rest: 'Rest day' }

function statusLine(d: PlanDay): string {
  if (d.status !== 'done') return STATUS_LINE[d.status]
  const v = d.verdict === 'better' ? 'Better' : d.verdict === 'worse' ? 'Worse' : d.verdict === 'in_line' ? 'In line' : null
  return ['Done', v, d.targets ? `${d.targets.hit}/${d.targets.of} hit` : null].filter(Boolean).join(' · ')
}

/** "Half Marathon Plan with Garmin Run Coach" → "Half Marathon Plan". */
function planName(name: string): string {
  return name.replace(/\s+with Garmin.*$/i, '')
}

function PlanHero({ a, pw }: { a: Ambient; pw: PlanWeek | null }) {
  const p = pw?.plan ?? a.today_workout?.plan ?? null
  const weeksLeft = p?.end ? Math.ceil((new Date(`${p.end}T12:00:00`).getTime() - Date.now()) / (7 * 86400000)) : null
  return (
    <section className="card hero stripes">
      <div className="hero-grid">
        <div className="stack" style={{ gap: 6 }}>
          <div className="label">Training plan · from Garmin Connect</div>
          <h1 className="display hero-title" style={{ fontStyle: 'italic' }}>{p ? planName(p.name) : 'This week'}</h1>
          <div className="hero-sub">
            {[p?.week && p.weeks ? `Week ${p.week} of ${p.weeks}` : null,
              p?.end ? `ends ${dayLabel(p.end)}` : null,
              pw ? `${pw.done} of ${pw.due} done so far` : null].filter(Boolean).join(' · ')}
          </div>
        </div>
        {p?.weeks && p.week ? (
          <div className="plan-progress" aria-label={`Week ${p.week} of ${p.weeks}`}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className="label">Plan progress</span>
              {weeksLeft != null && weeksLeft > 0 && <span className="label" style={{ color: 'var(--volt)' }}>{weeksLeft} weeks to go</span>}
            </div>
            <div className="plan-weeks" style={{ gridTemplateColumns: `repeat(${p.weeks}, minmax(0, 1fr))` }}>
              {Array.from({ length: p.weeks }, (_, i) => (
                <div key={i} className={`plan-wk${i + 1 < p.week! ? ' past' : i + 1 === p.week ? ' now' : ''}`}>
                  <i /><span className="num">{i + 1}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}

function WeekCards({ pw }: { pw: PlanWeek }) {
  const nav = useNavigate()
  return (
    <section className="stack" style={{ gap: 10 }}>
      <div className="card-title" style={{ margin: 0 }}>{new Date(`${pw.start}T12:00:00`).getDay() === 0 ? 'The next 7 days' : 'This week'}</div>
      <div className="plan-days">
        {pw.days.map(d => {
          const body = (
            <>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <span className="label pd-day">{dayLabel(d.day)}</span>
                <StatusMark status={d.status} size={24} />
              </div>
              <div className="pd-title">{d.title ?? 'Rest'}</div>
              <div className="pd-sub">{d.status === 'rest' ? 'Recover' : [shortDuration(d.est_duration_s), phraseLabel(d.phrase)].filter(Boolean).join(' · ')}</div>
              <div className="pd-shape">{d.steps?.length ? <WorkoutShape steps={d.steps} height={40} easy={isEasy(d.phrase)} /> : null}</div>
              <div className={`pd-status st-${d.status}`}>{statusLine(d)}</div>
            </>
          )
          return d.status === 'done' && d.session_id
            ? <button key={d.day} className={`card plan-day st-${d.status}`} onClick={() => nav(`/session/${encodeURIComponent(d.session_id!)}`)}>{body}</button>
            : <div key={d.day} className={`card plan-day st-${d.status}`}>{body}</div>
        })}
      </div>
    </section>
  )
}

function Content({ a }: { a: Ambient }) {
  const pw = a.plan_week ?? null
  const end = pw ? new Date(new Date(`${pw.start}T12:00:00`).getTime() + 7 * 86400000).toISOString().slice(0, 10) : ''
  const later = a.upcoming.filter(u => u.day >= end)
  return (
    <div className="detail">
      <PlanHero a={a} pw={pw} />
      {pw && <WeekCards pw={pw} />}
      <Today a={a} />
      <Upcoming items={later} />
    </div>
  )
}

function Today({ a }: { a: Ambient }) {
  const nav = useNavigate()
  const w: PlannedWorkout | null = a.today_workout
  const ss = a.sweet_spot
  const s = a.streak
  if (!w) {
    return (
      <section className="card">
        <div className="card-title">Today</div>
        <div className="display" style={{ fontSize: 34 }}>Nothing planned — a rest day.</div>
      </section>
    )
  }
  const ready = readyLines(a)
  const workSteps = w.steps.filter(x => x.kind === 'interval')
  const workSec = workSteps.reduce((t, x) => t + (x.duration_s ?? 0), 0)
  const after = ss && w.est_load != null && !w.done ? ss.load + w.est_load : null
  return (
    <>
      <section className="card hero">
        <div className="hero-grid">
          <div className="stack" style={{ gap: 8 }}>
            <div className="label row" style={{ gap: 8 }}>
              <SportIcon sport={w.sport} size={18} /> {dayLabel(w.day)} · today in your Garmin plan
            </div>
            <h2 className="display hero-title" style={{ color: 'var(--volt)', fontSize: 56 }}>{w.title}{w.est_duration_s ? ` · ${minutes(w.est_duration_s)}` : ''}</h2>
            {w.description && <div className="hero-sub">“{w.description}”</div>}
            <div className="row" style={{ gap: 8 }}>
              {w.done
                ? <span className="pill tone-better"><Check size={15} /> Done{w.done.linked ? ' · started from the workout' : ''}</span>
                : <span className="tag garmin"><Check size={14} /> On your watch · synced from Garmin Connect</span>}
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
          <WorkoutShape steps={w.steps} height={190} easy={isEasy(w.phrase)} labels={x => x.kind === 'interval' ? targetText(x) : null} />
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
                    <td><span className="step-name"><i style={{ background: stepLook(x, isEasy(w.phrase)).color }} />{stepKindLabel(x.kind)}</span>{x.description ? <span className="muted"> · {x.description}</span> : null}</td>
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
    </>
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

function Upcoming({ items }: { items: Ambient['upcoming'] }) {
  if (!items.length) return null
  return (
    <section className="stack" style={{ gap: 10 }}>
      <div className="card-title" style={{ margin: 0 }}>After that <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>· Garmin Coach adapts the coming days to your readiness</span></div>
      <div className="upcoming">
        {items.slice(0, 4).map(u => (
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

export function PlanDetail() {
  const { user } = useParams()
  const { wall } = useApp()
  const own = wall && wall.mode !== 'setup' && wall.user_id === user ? wall.ambient : null
  const { data } = useFetch(() => own ? Promise.resolve(own) : api.ambient(user!), [user, own])
  const a = own ?? data
  if (!a) return <div className="muted">Loading…</div>
  return <Content a={a} />
}
