import { ChevronRight, Flame, Loader2, RefreshCw, Zap } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Ambient, Streak as StreakData } from '../../api'
import { Buddy } from '../../components/Buddy'
import { SportIcon, TrendPill, VerdictIcon } from '../../components/icons'
import { improvedCount } from '../../components/Improvements'
import { StatusMark, shortDuration, weekday } from '../../components/WeekStrip'
import { WorkoutShape } from '../../components/WorkoutShape'
import { ago, distance, duration, hoursMinutes, num, SPORT_LABEL, VERDICT_LABEL, when } from '../../format'
import { feedbackText, headline, isEasy, minutes, READINESS_LEVEL, readinessTitle, workoutSummary } from '../../mission'
import { planName, SPORT_COLOR, tileContent } from '../../views/WallAmbient'
import { usePhone, seenStore } from '../ctx'
import { Avatar, Card, FormNumbers, SweetBar } from '../parts'
import type { Note } from '../util'
import { bodyBatteryNote, hrvBand, isFresh, MAIN_SPORTS, runPace, sweetHint, VERDICT_COLOR } from '../util'

function Header() {
  const { me, ambient: a, syncJob, syncNow } = usePhone()
  const today = new Date().toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  const sync = a?.sync
  return (
    <header className="ph-head">
      <Link to="/me" aria-label={`Me — ${me.name}`}><Avatar user={me} /></Link>
      <div className="ph-head-name">
        <span className="ph-name">{me.name}</span>
        <span className="ph-foot">{today}</span>
      </div>
      <button className={`ph-sync${sync?.stale || sync?.login_expired ? ' warn' : ''}`} onClick={syncNow} disabled={!!syncJob}
              aria-label={syncJob ? 'Syncing with Garmin' : `Sync now — last synced ${ago(sync?.last_success ?? null)}`}>
        {syncJob ? <Loader2 size={16} className="spin" aria-hidden /> : <RefreshCw size={16} aria-hidden />}
        {syncJob ? 'Syncing' : sync?.login_expired ? 'Login expired' : ago(sync?.last_success ?? null)}
      </button>
    </header>
  )
}

/** A fresh workout's verdict, small: the word, the score, one line, and the way in. */
function VerdictHero({ a }: { a: Ambient }) {
  const lw = a.last_workout!
  const s = a.recent.find(r => r.id === lw.id)
  const items = lw.improvements ?? []
  const color = VERDICT_COLOR[lw.verdict]
  const stats = s ? [s.distance_m ? distance(s.distance_m, s.sport) : null, duration(s.duration_s), runPace(s)]
    .filter(Boolean).join(' · ') : ''
  return (
    <Link to={`/verdict/${encodeURIComponent(lw.id)}`} className="ph-hero" style={{ borderColor: color }}>
      <div className="ph-row">
        {!seenStore.has(lw.id) && <span className="ph-new">NEW</span>}
        <span className="ph-foot">{lw.name ?? SPORT_LABEL[lw.sport]} · {when(lw.start_time).toLowerCase()}</span>
      </div>
      <div className="ph-row" style={{ gap: 10 }}>
        <VerdictIcon verdict={lw.verdict} size={32} strokeWidth={2.6} color={color} />
        <span className="ph-verdict-word" style={{ color }}>{VERDICT_LABEL[lw.verdict]}</span>
        {items.length > 0 && (
          <span className="ph-score"><b className="num">{improvedCount(items)}/{items.length}</b><span>improved</span></span>
        )}
      </div>
      <p className="ph-secondary">{lw.headline}</p>
      <div className="ph-row">
        <span className="num ph-foot">{stats}</span>
        <span className="ph-more">Verdict <ChevronRight size={16} aria-hidden /></span>
      </div>
    </Link>
  )
}

function Week({ a }: { a: Ambient }) {
  const pw = a.plan_week
  if (!pw) return null
  return (
    <div className="ph-week" role="group" aria-label="Training plan this week">
      {pw.days.map(d => (
        <Link key={d.day} to={`/plan?day=${d.day}`} className={`ph-day st-${d.status}`}
              aria-label={`${weekday(d.day)} ${d.title ?? 'rest'} ${d.status}`}>
          <span className="ph-day-name">{weekday(d.day)}</span>
          <StatusMark status={d.status} size={20} />
          <span className="ph-day-bar" style={{ background: d.sport ? SPORT_COLOR[d.sport] : 'transparent' }} />
          <span className="ph-day-dur num">{d.status === 'rest' ? 'rest' : shortDuration(d.est_duration_s)}</span>
        </Link>
      ))}
    </div>
  )
}

function Mission({ a, fresh }: { a: Ambient; fresh: boolean }) {
  const pw = a.plan_week
  const h = headline(a)
  const w = a.today_workout
  const lw = a.last_workout
  const b = a.buddy
  return (
    <>
      <Card className="ph-mission">
        <div className="ph-row">
          <Zap size={18} color="var(--volt)" strokeWidth={2.2} aria-hidden />
          <span className="ph-label">Today’s mission</span>
          {pw?.plan && (
            <span className="ph-label ph-right" style={{ color: 'var(--text-2)', letterSpacing: '0.08em' }}>
              {planName(pw.plan.name)}{pw.plan.week && pw.plan.weeks ? ` · wk ${pw.plan.week}/${pw.plan.weeks}` : ''}
            </span>
          )}
        </div>
        <h1 className="ph-title" style={{ color: 'var(--volt)' }}>{h.title}</h1>
        <p className="ph-secondary" style={{ margin: 0 }}>{h.sub}</p>
        {w && !w.done && (
          <Link to="/plan" className="ph-today-wo">
            <div className="ph-row">
              <span className="ph-label" style={{ color: 'var(--volt)' }}>Today</span>
              <span className="ph-right num">{minutes(w.est_duration_s)}</span>
            </div>
            <span className="ph-h3">{w.title}</span>
            {w.steps.length > 0 && <WorkoutShape steps={w.steps} height={44} easy={isEasy(w.phrase)} />}
            {workoutSummary(w).length > 0 && <span className="ph-foot">{workoutSummary(w).join(' · ')}</span>}
            <span className="ph-more">Steps <ChevronRight size={16} aria-hidden /></span>
          </Link>
        )}
        <Week a={a} />
        {b && (
          <div className="ph-buddy">
            <Buddy animal={b.animal} mood={b.mood} size={64} pettable />
            <div className="ph-bubble">{b.line}</div>
          </div>
        )}
      </Card>
      {!fresh && lw && (
        <Link to={`/verdict/${encodeURIComponent(lw.id)}`} className="ph-card ph-last">
          <VerdictIcon verdict={lw.verdict} size={26} color={VERDICT_COLOR[lw.verdict]} />
          <div className="ph-grow">
            <span className="ph-label">Last session · {when(lw.start_time)}</span>
            <span className="ph-ellipsis">{lw.name ?? SPORT_LABEL[lw.sport]} — <b style={{ color: VERDICT_COLOR[lw.verdict] }}>{VERDICT_LABEL[lw.verdict]}</b></span>
          </div>
          <ChevronRight size={20} color="var(--faint)" aria-hidden />
        </Link>
      )}
    </>
  )
}

/** Last night's HRV against the normal range. */
function hrvNote(hrv: number | null | undefined, band: [number, number] | null): Note | null {
  if (hrv == null || !band) return null
  if (hrv < band[0]) return { text: '▼ below range', tone: 'worse' }
  if (hrv > band[1]) return { text: '▲ above range', tone: 'better' }
  return { text: 'in range', tone: 'better' }
}

/** Resting HR against the usual: lower is better. */
function rhrNote(rhr: number | null | undefined, usual: number | null | undefined): Note | null {
  if (rhr == null || usual == null) return null
  if (Math.abs(rhr - usual) < 1) return { text: 'as usual', tone: 'inline' }
  const lower = rhr < usual
  return { text: `${lower ? '▼' : '▲'} ${Math.abs(Math.round(rhr - usual))}`, tone: lower ? 'better' : 'worse' }
}

function Recovery({ a }: { a: Ambient }) {
  const r = a.readiness
  const h = a.health_latest
  const C = 2 * Math.PI * 42
  const vo2 = a.vo2max.at(-1)?.value
  const tiles = [
    { label: 'HRV', v: num(h.hrv_last_night), unit: 'ms', metric: 'hrv', note: hrvNote(h.hrv_last_night, hrvBand(h)) },
    { label: 'Resting HR', v: num(h.rhr), unit: 'bpm', metric: 'rhr', note: rhrNote(h.rhr, a.health_baseline.rhr) },
    { label: 'Sleep', v: hoursMinutes(h.sleep_total_min).replace('h ', ':').replace('m', ''), unit: 'h', metric: 'sleep',
      note: h.sleep_score != null ? { text: `Score ${num(h.sleep_score)}`, tone: 'muted' } : null },
    // Intervals.icu has no Body Battery (Garmin keeps it to itself): steps instead
    a.source === 'intervals'
      ? { label: 'Steps', v: num(h.steps), unit: '', metric: 'steps', note: null }
      : { label: 'Body Battery', v: num(h.bb_max), unit: '', metric: 'body_battery', note: bodyBatteryNote(h.bb_max) },
  ]
  return (
    <Card>
      <div className="ph-row" style={{ gap: 14 }}>
        <div className="ph-ring" aria-label={r ? `${readinessTitle(r)} ${r.score}` : 'No readiness today'}>
          <svg width="72" height="72" viewBox="0 0 100 100" aria-hidden>
            <circle cx="50" cy="50" r="42" fill="none" stroke="var(--border)" strokeWidth="10" strokeDasharray={r ? undefined : '6 8'} />
            {r && <circle cx="50" cy="50" r="42" fill="none" stroke="var(--volt)" strokeWidth="10" strokeLinecap="round"
                          strokeDasharray={`${C * r.score / 100} ${C}`} transform="rotate(-90 50 50)" />}
          </svg>
          <b className="num">{r ? r.score : '–'}</b>
        </div>
        <div className="ph-grow">
          <span className="ph-label">{readinessTitle(r)}</span>
          <span className="ph-h3">{r ? READINESS_LEVEL[r.level ?? ''] ?? r.level ?? '—' : 'No score today'}</span>
          <span className="ph-foot">
            {[r ? feedbackText(r.feedback) : null, vo2 != null ? `VO₂max ${vo2.toFixed(1)}` : null].filter(Boolean).join(' · ')}
          </span>
        </div>
      </div>
      <div className="ph-grid2">
        {tiles.map(t => (
          <Link key={t.label} to={`/trends/health?metric=${t.metric}`} className="ph-tile">
            <span className="ph-label sm">{t.label}</span>
            <span><b className="num ph-tile-v">{t.v}</b>{t.unit && <span className="ph-unit"> {t.unit}</span>}</span>
            {t.note && <span className={`ph-foot tone-${t.note.tone}`}>{t.note.text}</span>}
          </Link>
        ))}
      </div>
    </Card>
  )
}

function Load({ a }: { a: Ambient }) {
  const ss = a.sweet_spot
  return (
    <Link to="/trends" className="ph-card ph-link-card">
      <div className="ph-row"><span className="ph-h3">Training load</span><span className="ph-more ph-right">Details <ChevronRight size={16} aria-hidden /></span></div>
      <FormNumbers form={a.form} />
      {ss && (
        <>
          <div className="ph-row"><span className="ph-label sm">This week · TRIMP</span>
            <span className="ph-right"><b className="num">{ss.load}</b> <span className="num ph-unit">/ {ss.low}–{ss.high}</span></span></div>
          <SweetBar a={a} />
          <span className="ph-foot">{sweetHint(a)}</span>
        </>
      )}
    </Link>
  )
}

function Streak({ a }: { a: Ambient }) {
  const s = a.streak
  const n = s.history.length
  return (
    <Card>
      <div className="ph-row" style={{ gap: 10 }}>
        <Flame size={30} color="var(--accent)" aria-hidden />
        <span className="ph-streak-n">{s.weeks}</span>
        <div className="ph-grow"><span className="ph-h3">Week streak</span><span className="ph-foot">{s.min_sessions}+ workouts every week</span></div>
      </div>
      <div className="ph-streak" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }} aria-label={`Workouts per week, last ${n} weeks`}>
        {s.history.map((w, i) => (
          <div key={w.week} className={i === n - 1 ? 'now' : ''}>
            {Array.from({ length: s.min_sessions }, (_, k) => <i key={k} className={s.min_sessions - k <= w.count ? 'on' : ''} />)}
          </div>
        ))}
      </div>
      <span className="ph-secondary" style={{ color: 'var(--accent-2)', fontWeight: 600 }}>{streakLine(s)}</span>
    </Card>
  )
}

/** What this week still needs for the streak. */
function streakLine(s: StreakData): string {
  if (s.needed === 0) return `This week counts — ${s.this_week} workouts`
  if (s.days_left + 1 < s.needed) return 'Not enough days left — next week starts a new one'
  return `${s.needed} more workout${s.needed > 1 ? 's' : ''} this week ${s.weeks ? 'keeps it alive' : 'starts a streak'}`
}

function Sports({ a }: { a: Ambient }) {
  return (
    <section className="ph-section">
      <span className="ph-label" style={{ padding: '0 4px' }}>Every sport</span>
      <div className="ph-grid2">
        {MAIN_SPORTS.map(sp => {
          const t = a.trends[sp]
          const c = t ? tileContent(sp, t) : null
          const body = (
            <>
              <span className="ph-row" style={{ gap: 6 }}><SportIcon sport={sp} size={18} color={SPORT_COLOR[sp]} /><span className="ph-label sm" style={{ color: 'var(--text-2)' }}>{SPORT_LABEL[sp]}</span></span>
              {c ? <>
                <span><b className="ph-sport-big">{c.big}</b>{c.unit && <span className="ph-unit"> {c.unit}</span>}</span>
                <span className="ph-caption">{c.caption}</span>
                <TrendPill trend={c.trend} stale={c.stale} />
              </> : <span className="ph-caption">No sessions yet</span>}
            </>
          )
          const style = { borderTopColor: SPORT_COLOR[sp] }
          return t
            ? <Link key={sp} to={`/trends/sport/${sp}`} className="ph-card ph-sport" style={style}
                    aria-label={`${SPORT_LABEL[sp]} — all sessions`}>{body}</Link>
            : <div key={sp} className="ph-card ph-sport" style={style}>{body}</div>
        })}
      </div>
    </section>
  )
}

export function Today() {
  const { ambient } = usePhone()
  const a = ambient!
  const fresh = !!a.last_workout && isFresh(a.last_workout.start_time)
  return (
    <div className="ph-stack">
      <Header />
      {fresh && <VerdictHero a={a} />}
      <Mission a={a} fresh={fresh} />
      <Recovery a={a} />
      <Load a={a} />
      <Streak a={a} />
      <Sports a={a} />
    </div>
  )
}
