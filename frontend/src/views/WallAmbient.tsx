import { ChevronRight, Flame, Zap } from 'lucide-react'
import { useLayoutEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Ambient, Sport, SportTrend } from '../api'
import { Buddy } from '../components/Buddy'
import { SportIcon, VerdictPill } from '../components/icons'
import { Sparkline } from '../components/Sparkline'
import { WeekStrip } from '../components/WeekStrip'
import { formState, hoursMinutes, num, signed, SPORT_LABEL } from '../format'
import { READINESS_LEVEL, feedbackText, headline, paceStr } from '../mission'
import './Wall.css'

const SPORTS: Sport[] = ['running', 'cycling', 'swimming', 'strength']
const SPORT_COLOR: Record<Sport, string> = {
  running: 'var(--run)', cycling: 'var(--ride)', swimming: 'var(--swim)', strength: 'var(--gym)', other: 'var(--muted)',
}

/** "Half Marathon Plan with Garmin Run Coach" → "Half Marathon Plan" — the wall has little room. */
function planName(name: string): string {
  return name.replace(/\s+with Garmin.*$/i, '')
}

function shortWhen(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).setHours(0, 0, 0, 0)) / 86400000)
  return days <= 0 ? 'Today' : days === 1 ? 'Yesterday' : `${days} d ago`
}

/* ------------------------------------------------------------------------------------------ */

export const MOOD_LABEL: Record<string, string> = {
  happy: 'happy', content: 'content', sleepy: 'sleepy', overjoyed: 'overjoyed', hungry: 'hungry', asleep: 'asleep',
}

/** Largest font size (max → min px) at which `text` stays on one line in its element. */
function useFitText<T extends HTMLElement>(text: string, max: number, min: number): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null)
  const [size, setSize] = useState(max)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const fit = () => {
      let s = max
      el.style.fontSize = `${s}px`
      while (s > min && el.scrollWidth > el.clientWidth + 1) {
        s -= 4
        el.style.fontSize = `${s}px`
      }
      el.style.fontSize = ''  // the CSS caps it by the screen height too (--fit)
      setSize(s)
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    document.fonts?.ready.then(fit).catch(() => {})
    return () => ro.disconnect()
  }, [text, max, min])
  return [ref, size]
}

function Mission({ a }: { a: Ambient }) {
  const nav = useNavigate()
  const pw = a.plan_week
  const h = headline(a)
  const open = (day: string) => nav(`/u/${a.user_id}/plan?day=${day}`)
  const b = a.buddy
  const [titleRef, titleSize] = useFitText<HTMLHeadingElement>(h.title, pw ? 80 : 112, 56)
  return (
    <section className={`card mission stripes${pw ? '' : ' no-workout'}${b ? ' has-buddy' : ''}`}>
      <div className="mission-main">
      <div className="mission-label">
        <Zap size={18} color="var(--volt)" strokeWidth={2.4} /> Today’s mission
        {pw?.plan && (
          <span className="mission-plan">
            {planName(pw.plan.name)}{pw.plan.week && pw.plan.weeks ? ` · week ${pw.plan.week}/${pw.plan.weeks}` : ''}
          </span>
        )}
      </div>
      <h1 ref={titleRef} className="display mission-title" style={{ '--fit': `${titleSize}px` } as React.CSSProperties}>{h.title}</h1>
      {!pw && <p className="mission-sub">{h.sub}</p>}  {/* with the week strip there's no room for it; the buddy says it */}
      {pw && <WeekStrip week={pw} onOpen={open} />}
      </div>
      {b && (
        <aside className="mission-buddy" aria-label={`Your ${b.animal} is ${MOOD_LABEL[b.mood]}`}>
          <div className="buddy-says">{b.line}</div>
          <Buddy animal={b.animal} mood={b.mood} size={150} pettable />
        </aside>
      )}
    </section>
  )
}

function ReadinessCard({ a }: { a: Ambient }) {
  const nav = useNavigate()
  const r = a.readiness
  const h = a.health_latest
  const b = a.health_baseline
  const C = 2 * Math.PI * 44
  const vo2 = a.vo2max.at(-1)?.value
  const vo2Then = a.vo2max.length > 1 ? [...a.vo2max].reverse().find(v => (Date.parse(a.vo2max.at(-1)!.day) - Date.parse(v.day)) / 86400000 >= 42)?.value : undefined
  const band = h.hrv_baseline_low && h.hrv_baseline_high ? [h.hrv_baseline_low, h.hrv_baseline_high] : null
  const vitals = [
    {
      label: 'HRV', value: num(h.hrv_last_night), unit: 'ms', metric: 'hrv',
      delta: h.hrv_last_night == null ? null : band
        ? (h.hrv_last_night < band[0] ? { t: '▼ below range', c: 'worse' } : h.hrv_last_night > band[1] ? { t: '▲ above range', c: 'better' } : { t: 'in range', c: 'better' })
        : null,
    },
    {
      label: 'Resting HR', value: num(h.rhr), unit: 'bpm', metric: 'rhr',
      delta: h.rhr != null && b.rhr != null ? (Math.abs(h.rhr - b.rhr) < 1 ? { t: 'as usual', c: 'inline' }
        : { t: `${h.rhr < b.rhr ? '▼' : '▲'} ${Math.abs(Math.round(h.rhr - b.rhr))}`, c: h.rhr < b.rhr ? 'better' : 'worse' }) : null,
    },
    { label: 'Sleep', value: hoursMinutes(h.sleep_total_min).replace('h ', ':').replace('m', ''), unit: 'h', metric: 'sleep',
      delta: h.sleep_score != null ? { t: `Score ${num(h.sleep_score)}`, c: 'muted' } : null },
    { label: 'Body Battery', value: num(h.bb_max), unit: '', metric: 'body_battery',
      delta: h.bb_max != null ? { t: h.bb_max >= 85 ? 'Full' : h.bb_max >= 60 ? 'Good' : 'Low', c: h.bb_max >= 60 ? 'better' : 'worse' } : null },
  ]
  return (
    <section className="card readiness">
      <div className="readiness-head">
        <div className="ring" aria-label={r ? `Garmin training readiness ${r.score}` : 'No readiness from Garmin today'}>
          <svg width="104" height="104" viewBox="0 0 104 104">
            <circle cx="52" cy="52" r="44" fill="none" stroke="var(--border)" strokeWidth="10" strokeDasharray={r ? undefined : '6 8'} />
            {r && <circle cx="52" cy="52" r="44" fill="none" stroke="var(--volt)" strokeWidth="10" strokeLinecap="round"
                          strokeDasharray={`${C * r.score / 100} ${C}`} transform="rotate(-90 52 52)" />}
          </svg>
          <div className="ring-center">
            <b>{r ? r.score : '–'}</b>
            <span>{r ? '/ 100' : ''}</span>
          </div>
        </div>
        <div style={{ minWidth: 0 }}>
          <div className="label">Training readiness</div>
          {r ? (
            <>
              <div className="display readiness-level">{READINESS_LEVEL[r.level ?? ''] ?? r.level ?? '—'}</div>
              <div className="muted small">{feedbackText(r.feedback)}</div>
            </>
          ) : (
            <>
              <div className="readiness-none">No readiness from Garmin today</div>
            </>
          )}
          {vo2 != null && (
            <button className="vo2" onClick={() => nav(`/u/${a.user_id}/health/vo2max`)} aria-label={`VO2max ${vo2.toFixed(1)}, open the graph`}>
              <span className="label">VO₂max</span>
              <b className="num">{vo2.toFixed(1)}</b>
              {vo2Then != null && Math.abs(vo2 - vo2Then) >= 0.05 && (
                <span className={`small strong tone-${vo2 > vo2Then ? 'better' : 'worse'}`}>{vo2 > vo2Then ? '▲' : '▼'}{Math.abs(vo2 - vo2Then).toFixed(1)}</span>
              )}
              <span className="vo2-spark"><Sparkline values={a.vo2max.slice(-90).map(v => v.value)} height={22} color="var(--better)" /></span>
            </button>
          )}
        </div>
      </div>
      <div className="vitals">
        {vitals.map(v => (
          <button key={v.label} className="tile vital" onClick={() => nav(`/u/${a.user_id}/health/${v.metric}`)}>
            <div className="label">{v.label}</div>
            <div className="vital-row">
              <span className="num vital-v">{v.value}</span>
              {v.unit && <span className="muted small">{v.unit}</span>}
              {v.delta && <span className={`small strong tone-${v.delta.c}`}>{v.delta.t}</span>}
            </div>
          </button>
        ))}
      </div>
    </section>
  )
}

/** formState() labels, shortened for the card header. */
const SHORT_FORM: Record<string, string> = {
  'Very fresh — losing fitness': 'Very fresh', 'Productive training': 'Productive', 'Overreaching risk': 'Overreaching',
}

/** Change over the last 6 weeks (today vs. 42 days ago) of one PMC line. */
function change6w(pmc: Ambient['pmc'], k: 'fatigue' | 'form'): number | null {
  if (pmc.length < 43) return null
  return pmc[pmc.length - 1][k] - pmc[pmc.length - 43][k]
}

/** ▲/▼ with the size of a change, like the fitness indicator. Fatigue and form going up or down
 *  isn't good or bad by itself, so they stay neutral. */
function Change({ v }: { v: number | null }) {
  if (v == null) return null
  if (Math.abs(v) < 0.5) return <em className="tone-inline">●0</em>
  return <em className="tone-inline">{v > 0 ? '▲' : '▼'}{Math.abs(v).toFixed(0)}</em>
}

/** Where the zero line sits in MiniPmc, in % from the top (for its "0" label). */
function zeroPct(days: Ambient['pmc']): number {
  const vals = days.flatMap(d => [d.fitness, d.fatigue, d.form, 0])
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1
  return (3 + (1 - (0 - lo) / span) * 94)
}

/** 6 weeks of fitness (blue), fatigue (pink, dashed) and form (yellow) on one chart and one scale, with a zero line. */
function MiniPmc({ days }: { days: Ambient['pmc'] }) {
  if (days.length < 2) return null
  const W = 500, H = 100
  const vals = days.flatMap(d => [d.fitness, d.fatigue, d.form, 0])
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1
  const x = (i: number) => (i / (days.length - 1)) * W
  const y = (v: number) => 3 + (1 - (v - lo) / span) * (H - 6)
  const path = (k: 'fitness' | 'fatigue' | 'form') => days.map((d, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(d[k]).toFixed(1)}`).join('')
  return (
    <svg className="mini-pmc" viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" preserveAspectRatio="none" aria-hidden>
      {/* zero line: form above it = fresh, below = tired */}
      <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="#6b7585" strokeWidth={1.5} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
      <path d={`${path('fitness')}L${W} ${y(0)}L0 ${y(0)}Z`} fill="var(--fitness)" opacity={0.12} />
      <path d={path('form')} fill="none" stroke="var(--form)" strokeWidth={2.2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      <path d={path('fatigue')} fill="none" stroke="var(--fatigue)" strokeWidth={1.8} strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
      <path d={path('fitness')} fill="none" stroke="var(--fitness)" strokeWidth={3} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function LoadCard({ a }: { a: Ambient }) {
  const nav = useNavigate()
  const f = a.form
  const fs = formState(f?.form)
  const ss = a.sweet_spot
  const w = a.today_workout
  const planned = w && !w.done ? w.est_load ?? 0 : 0
  const max = ss ? Math.max(ss.high * 1.25, ss.load + planned) : 1
  const pct = (v: number) => `${Math.min(100, v / max * 100)}%`
  let hint = ''
  if (ss) {
    if (ss.load >= ss.high) hint = 'Above the sweet spot — take it easy.'
    else if (ss.load >= ss.low) hint = 'In the sweet spot. Nice.'
    else if (planned && ss.load + planned >= ss.low) hint = `Today’s ${w!.title} gets you there.`
    else hint = `~${Math.round((ss.low - ss.load) / 10) * 10} more to the sweet spot.`
  }
  return (
    <button className="card loadcard" onClick={() => nav(`/u/${a.user_id}/load`)}>
      <div className="card-head">
        <span className="display card-name">Training load</span>
        <span className="pmc-inline">
          <span><i style={{ background: 'var(--fitness)' }} />Fitness <b className="num">{num(f?.fitness)}</b>
            {a.fitness_change_6w != null && <em className={`tone-${a.fitness_change_6w >= 0.5 ? 'better' : a.fitness_change_6w <= -0.5 ? 'worse' : 'inline'}`}>
              {a.fitness_change_6w >= 0.5 ? '▲' : a.fitness_change_6w <= -0.5 ? '▼' : '●'}{Math.abs(a.fitness_change_6w).toFixed(0)}</em>}</span>
          <span><i className="dash" style={{ borderColor: 'var(--fatigue)' }} />Fatigue <b className="num">{num(f?.fatigue)}</b>
            <Change v={change6w(a.pmc, 'fatigue')} /></span>
          <span><i style={{ background: 'var(--form)' }} />Form <b className="num" style={{ color: 'var(--form)' }}>{signed(f?.form, 0)}</b>
            <Change v={change6w(a.pmc, 'form')} /><em className={`tone-${fs.tone}`}>{SHORT_FORM[fs.label] ?? fs.label}</em></span>
        </span>
        <span className="grow" />
        <span className="link">Details <ChevronRight size={16} /></span>
      </div>
      <div className="loadcard-body">
        <div className="pmc-chart">
          <div className="pmc-plot"><MiniPmc days={a.pmc.slice(-42)} /><span className="pmc-zero" style={{ top: `${zeroPct(a.pmc.slice(-42))}%` }}>0</span></div>
          <div className="pmc-axis"><span>6 weeks ago</span><span>today</span></div>
        </div>
        <div className="divider" />
        <div className="sweet">
          {ss ? (
            <>
              <div className="label sweet-label">This week · TRIMP</div>
              <div className="sweet-top">
                <span className="num sweet-v">{ss.load}</span>
                <span className="muted">/ <b className="num" style={{ color: 'var(--text)' }}>{ss.low}–{ss.high}</b></span>
              </div>
              <div className="sweet-bar" title="too easy · sweet spot · too much" aria-label={`${ss.load} of a ${ss.low} to ${ss.high} sweet spot`}>
                <i className="zone" style={{ left: pct(ss.low), width: `calc(${pct(ss.high)} - ${pct(ss.low)})` }} />
                <i className="over" style={{ left: pct(ss.high), right: 0 }} />
                <i className="fill" style={{ width: pct(ss.load) }} />
                {planned > 0 && <i className="plan" style={{ left: pct(ss.load), width: `calc(${pct(ss.load + planned)} - ${pct(ss.load)})` }} />}
              </div>
              <div className="sweet-hint">{hint}</div>
            </>
          ) : <div className="muted">No training load yet</div>}
        </div>
      </div>
    </button>
  )
}

function StreakCard({ a }: { a: Ambient }) {
  const s = a.streak
  const n = s.history.length
  return (
    <section className="card streak">
      <div className="streak-head">
        <Flame size={40} color="var(--accent)" strokeWidth={2} />
        <span className="streak-n">{s.weeks}</span>
        <div style={{ minWidth: 0 }}>
          <div className="display streak-name">Week streak</div>
          <div className="muted small">{s.min_sessions}+ workouts every week</div>
        </div>
      </div>
      <div className="streak-weeks" aria-label={`Workouts per week, last ${n} weeks`}>
        {s.history.map((w, i) => {
          const now = i === n - 1
          return (
            <div key={w.week} className={`streak-week${now ? ' now' : ''}`}>
              <div className="pips">
                {Array.from({ length: s.min_sessions }, (_, k) => <i key={k} className={k < w.count ? 'on' : ''} />)}
              </div>
              <span>{now ? 'Now' : `W${weekNo(w.week)}`}</span>
            </div>
          )
        })}
      </div>
      <div className="streak-note">
        {s.needed === 0 ? `This week counts — ${s.this_week} workouts`
          : s.days_left + 1 < s.needed ? 'Not enough days left this week — next week starts a new one'
          : `${s.needed} more workout${s.needed > 1 ? 's' : ''} this week ${s.weeks ? 'keeps it alive' : 'starts a streak'}`}
      </div>
    </section>
  )
}

function weekNo(iso: string): number {
  const d = new Date(iso)
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7))
  const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1))
  return Math.ceil(((t.getTime() - y.getTime()) / 86400000 + 1) / 7)
}

/* Sport tiles: one big number in real units, its trend, and the last verdict. */
function tileContent(sport: Sport, t: SportTrend): { big: string; unit?: string; caption: string; extra?: string; spark: number[]; tone: string } {
  const st = t.status
  if (sport === 'running' && st?.pace_s_per_km) {
    const c = st.change_s_per_km
    const cad = t.cadence
    const trend = c == null ? 'not enough runs for a trend' : Math.abs(c) < 2 ? 'steady over 6 wks'
      : `${c > 0 ? '▲' : '▼'} ${Math.abs(c).toFixed(0)} s/km ${c > 0 ? 'faster' : 'slower'} in 6 wks`
    return {
      big: paceStr(st.pace_s_per_km), unit: '/km',
      caption: `at ${num(st.ref_hr)} bpm · ${trend}`,
      extra: cad ? `Cadence ${cad.spm} spm${cad.change ? ` ${cad.change > 0 ? '▲' : '▼'}${Math.abs(cad.change)}` : ''}` : undefined,
      spark: st.points.map(p => -p.value), tone: c == null ? 'muted' : c >= 2 ? 'better' : c <= -2 ? 'worse' : 'inline',
    }
  }
  if (sport === 'cycling' && st && st.w_per_beat != null) {
    const c = st.w_per_beat_change_pct
    const trend = c == null ? 'too few power rides for a trend' : Math.abs(c) < 1 ? 'steady over 3 months'
      : `${c > 0 ? '▲' : '▼'} ${Math.abs(c).toFixed(1)} % in 3 months`
    return {
      big: st.w_per_beat.toFixed(2), unit: 'W/beat',
      caption: trend,
      extra: st.ftp_wkg ? `FTP ${st.ftp_wkg.toFixed(1)} W/kg` : undefined,
      spark: st.points.map(p => p.value), tone: c == null ? 'muted' : c >= 1 ? 'better' : c <= -1 ? 'worse' : 'inline',
    }
  }
  // a trend this steep comes from too few sessions: don't show it on the wall
  const raw6 = t.pct_per_week == null ? null : t.pct_per_week * 6
  const pct6 = raw6 != null && Math.abs(raw6) <= 30 ? raw6 : null
  if (sport === 'swimming' && t.points.length) {
    // pace per 100 m (seconds): the big number is the typical pace of the last swims; + % = faster
    const last = t.points.slice(-3).map(p => p.value).sort((x, y) => x - y)
    const trend = pct6 == null ? 'not enough swims for a trend' : Math.abs(pct6) < 1.2 ? 'steady over 6 wks'
      : `${pct6 > 0 ? '▲' : '▼'} ${Math.abs(pct6).toFixed(1)} % ${pct6 > 0 ? 'faster' : 'slower'} in 6 wks`
    return {
      big: paceStr(last[Math.floor(last.length / 2)]), unit: '/100 m', caption: trend,
      spark: t.points.map(p => -p.value), tone: pct6 == null ? 'muted' : pct6 >= 1.2 ? 'better' : pct6 <= -1.2 ? 'worse' : 'inline',
    }
  }
  return {
    big: pct6 == null ? '—' : signed(pct6, 1, '%'),
    caption: pct6 == null ? 'Not enough sessions for a trend yet' : `${t.metric ?? (sport === 'strength' ? 'e1RM' : 'trend')} · 6 wks`,
    spark: t.points.map(p => p.value), tone: pct6 == null ? 'muted' : pct6 >= 1.2 ? 'better' : pct6 <= -1.2 ? 'worse' : 'inline',
  }
}

function SportTile({ a, sport }: { a: Ambient; sport: Sport }) {
  const nav = useNavigate()
  const t = a.trends[sport]
  const c = t ? tileContent(sport, t) : null
  return (
    <button className="card sport-tile" style={{ '--sc': SPORT_COLOR[sport] } as React.CSSProperties}
            onClick={() => nav(`/u/${a.user_id}/sport/${sport}`)}>
      <div className="sport-tile-head">
        <SportIcon sport={sport} size={22} color={SPORT_COLOR[sport]} />
        <span className="sport-name">{SPORT_LABEL[sport]}</span>
        <span className="grow" />
        {t && <span className="muted small nowrap">{shortWhen(t.last_time)}</span>}
      </div>
      {c ? (
        <>
          <div className="display sport-big">{c.big}{c.unit && <span className="unit">{c.unit}</span>}</div>
          <div className="muted small ellipsis">{c.caption}</div>
          {c.extra && <div className="small ellipsis cadence">{c.extra}</div>}
          <div className="sport-spark"><Sparkline values={c.spark} height={24} color={SPORT_COLOR[sport]} /></div>
          <div className="sport-foot"><VerdictPill verdict={t!.last_verdict} /></div>
        </>
      ) : <div className="muted" style={{ marginTop: 8 }}>No sessions yet</div>}
    </button>
  )
}

export function WallAmbient({ ambient: a }: { ambient: Ambient }) {
  return (
    <div className="ambient">
      <Mission a={a} />
      <ReadinessCard a={a} />
      <LoadCard a={a} />
      <StreakCard a={a} />
      <div className="sport-tiles">
        {SPORTS.map(s => <SportTile key={s} a={a} sport={s} />)}
      </div>
    </div>
  )
}

