import { BatteryMedium, BedDouble, Brain, CheckCircle2, Gauge, HeartPulse, TrendingUp, Waves } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { Ambient, ProgressItem, Sport } from '../api'
import { SportIcon, VerdictPill } from '../components/icons'
import { Sparkline } from '../components/Sparkline'
import { distance, duration, formState, hoursMinutes, num, signed, SPORT_LABEL, TYPE_LABEL, when } from '../format'
import './Wall.css'

function vsBaseline(v: number | null | undefined, base: number | null | undefined, lowerIsBetter = false, unit = '') {
  if (v == null || base == null) return <span className="muted vs">no baseline yet</span>
  const d = v - base
  const good = lowerIsBetter ? d < 0 : d > 0
  const tone = Math.abs(d) < Math.abs(base) * 0.03 ? 'inline' : good ? 'better' : 'worse'
  return <span className={`vs tone-${tone}`}>{signed(d, 0, unit)} vs usual {num(base)}{unit}</span>
}

const SPORTS: Sport[] = ['running', 'cycling', 'swimming', 'strength']
const TONE: Record<ProgressItem['tone'], string> = { improving: 'better', steady: 'inline', declining: 'worse' }
const ARROW: Record<ProgressItem['tone'], string> = { improving: '▲', steady: '●', declining: '▼' }

function shortWhen(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)
  return days <= 0 ? 'today' : days === 1 ? 'yesterday' : `${days}d ago`
}

export function WallAmbient({ ambient: a }: { ambient: Ambient }) {
  const nav = useNavigate()
  const u = a.user_id
  const h = a.health_latest
  const b = a.health_baseline
  const fs = formState(a.form?.form)
  const sleepTotal = h.sleep_total_min ?? 0
  const hrvBand: [number, number] | null = h.hrv_baseline_low && h.hrv_baseline_high ? [h.hrv_baseline_low, h.hrv_baseline_high] : null
  const series = a.health_series
  const p = a.progress ?? { weeks: 6, items: [], improving: 0, declining: 0 }

  // precise VO2max change over ~6 weeks (latest vs. the last value at least 42 days earlier)
  const vo2Last = a.vo2max.at(-1)
  const vo2Then = vo2Last && [...a.vo2max].reverse().find(v => (Date.parse(vo2Last.day) - Date.parse(v.day)) / 86400000 >= 42)
  const vo2Change = vo2Last && vo2Then ? vo2Last.value - vo2Then.value : null

  const weekSports = Array.from(new Set([...Object.keys(a.week), ...Object.keys(a.last_week)])) as Sport[]
  const maxDur = Math.max(1, ...weekSports.map(s => Math.max(a.week[s]?.duration_s ?? 0, a.last_week[s]?.duration_s ?? 0)))

  return (
    <div className="ambient">
      {/* Fitness progress: the headline of the wall */}
      <div className="card span-7 progress-card">
        <div className="between">
          <div className="card-title" style={{ margin: 0 }}><TrendingUp size={18} /> Fitness progress · last {p.weeks} weeks</div>
          {p.items.length > 0 && (
            <span className={`progress-sum tone-${p.improving > p.declining ? 'better' : p.declining > p.improving ? 'worse' : 'inline'}`}>
              Improving in {p.improving} of {p.items.length}
            </span>
          )}
        </div>
        <div className="progress-body">
          <button className="progress-hero" onClick={() => nav(`/u/${u}/health/vo2max`)}>
            <div className="metric-label"><Waves size={14} /> VO₂max</div>
            <div className="big num">{num(vo2Last?.value, 1)}</div>
            {vo2Change != null
              ? <span className={`mid num tone-${vo2Change > 0.05 ? 'better' : vo2Change < -0.05 ? 'worse' : 'inline'}`} style={{ fontSize: 22 }}>
                  {signed(vo2Change, 1)}</span>
              : <span className="muted vs">no 6-week history yet</span>}
            <Sparkline values={a.vo2max.slice(-180).map(v => v.value)} height={40} />
          </button>
          <ul className="progress-list">
            {p.items.filter(i => i.key !== 'vo2max').slice(0, 5).map(i => (
              <li key={i.key}>
                <button onClick={() => nav(i.sport ? `/u/${u}/sport/${i.sport}` : i.link ? `/u/${u}/health/${i.link}` : `/u/${u}/load`)}>
                  <span className={`progress-dot tone-${TONE[i.tone]}`}>{ARROW[i.tone]}</span>
                  <span className="progress-label">{i.sport && <SportIcon sport={i.sport} size={16} />} {i.label}</span>
                  <span className={`num tone-${TONE[i.tone]}`}>{signed(i.change, i.dp, i.unit)}</span>
                </button>
              </li>
            ))}
            {p.items.length === 0 && <li className="muted">Needs a few weeks of data</li>}
          </ul>
        </div>
      </div>

      {/* Recovery */}
      <div className="card span-5">
        <div className="card-title"><HeartPulse size={18} /> Recovery today</div>
        <div className="recovery-grid">
          <button className="card" style={{ padding: 12 }} onClick={() => nav(`/u/${u}/health/hrv`)}>
            <div className="metric-label">HRV last night</div>
            <div className="mid num">{num(h.hrv_last_night)} <span className="muted" style={{ fontSize: 16 }}>ms</span></div>
            {hrvBand
              ? <span className={`vs tone-${h.hrv_last_night! < hrvBand[0] ? 'worse' : h.hrv_last_night! > hrvBand[1] ? 'inline' : 'better'}`}>
                  {h.hrv_last_night! < hrvBand[0] ? 'Below' : h.hrv_last_night! > hrvBand[1] ? 'Above' : 'Within'} baseline {hrvBand[0]}–{hrvBand[1]}
                </span>
              : vsBaseline(h.hrv_last_night, b.hrv_last_night)}
          </button>
          <button className="card" style={{ padding: 12 }} onClick={() => nav(`/u/${u}/health/rhr`)}>
            <div className="metric-label">Resting HR</div>
            <div className="mid num">{num(h.rhr)} <span className="muted" style={{ fontSize: 16 }}>bpm</span></div>
            {vsBaseline(h.rhr, b.rhr, true)}
          </button>
          <button className="card" style={{ padding: 12 }} onClick={() => nav(`/u/${u}/health/sleep`)}>
            <div className="metric-label"><BedDouble size={14} /> Sleep {h.sleep_score != null && <>· score {num(h.sleep_score)}</>}</div>
            <div className="mid num">{hoursMinutes(h.sleep_total_min)}</div>
            {sleepTotal > 0 && (
              <div className="sleep-bar" aria-label="Sleep stages: deep, REM, light, awake">
                <span style={{ width: `${(h.sleep_deep_min ?? 0) / sleepTotal * 100}%`, background: '#6366f1' }} />
                <span style={{ width: `${(h.sleep_rem_min ?? 0) / sleepTotal * 100}%`, background: '#38bdf8' }} />
                <span style={{ width: `${(h.sleep_light_min ?? 0) / sleepTotal * 100}%`, background: '#475569' }} />
                <span style={{ width: `${(h.sleep_awake_min ?? 0) / sleepTotal * 100}%`, background: '#f472b6' }} />
              </div>
            )}
          </button>
          <button className="card" style={{ padding: 12 }} onClick={() => nav(`/u/${u}/health/body_battery`)}>
            <div className="metric-label"><BatteryMedium size={14} /> Body Battery · <Brain size={14} /> Stress</div>
            <div className="mid num">{num(h.bb_max)} <span className="muted" style={{ fontSize: 16 }}>· {num(h.stress_avg)}</span></div>
            <Sparkline values={series.map(d => d.bb_max).filter((x): x is number => x != null).slice(-14)} height={28} />
          </button>
        </div>
      </div>

      {/* Per-sport improvement trends */}
      <div className="span-12 sport-cards">
        {SPORTS.map(s => {
          const t = a.trends[s]
          return (
            <button key={s} className="card sport-card" onClick={() => nav(`/u/${u}/sport/${s}`)}>
              <div className="between">
                <span className="card-title" style={{ margin: 0 }}><SportIcon sport={s} size={18} /> {SPORT_LABEL[s]}</span>
                {t && <VerdictPill verdict={t.last_verdict} />}
              </div>
              {t ? (
                <>
                  <Sparkline height={36} values={t.points.map(p => p.value)}
                             color={t.pct_per_week == null ? 'var(--muted)' : t.pct_per_week > 0.2 ? 'var(--better)' : t.pct_per_week < -0.2 ? 'var(--worse)' : 'var(--inline)'} />
                  <div className="between" style={{ fontSize: 15 }}>
                    <span className={t.pct_per_week == null ? 'muted' : t.pct_per_week > 0.2 ? 'tone-better' : t.pct_per_week < -0.2 ? 'tone-worse' : 'tone-inline'}>
                      {t.pct_per_week == null ? (s === 'strength' ? 'Tap for lifts' : 'Not enough data') : `${signed(t.pct_per_week, 1, '%')}/wk`}
                    </span>
                    <span className="muted" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{t.metric ?? 'e1RM'} · {shortWhen(t.last_time)}</span>
                  </div>
                </>
              ) : <div className="muted">No sessions yet</div>}
            </button>
          )
        })}
      </div>

      {/* Weekly volume */}
      <div className="card span-5">
        <div className="card-title">This week vs last week</div>
        <div className="week-rows">
          {weekSports.length === 0 && <div className="muted">No training yet this week</div>}
          {weekSports.map(s => {
            const cur = a.week[s]?.duration_s ?? 0
            const last = a.last_week[s]?.duration_s ?? 0
            return (
              <div key={s} className="week-row">
                <span className="row" style={{ gap: 6 }}><SportIcon sport={s} size={16} /> {SPORT_LABEL[s]}</span>
                <div className="week-bar" aria-label={`${duration(cur)} this week, ${duration(last)} last week`}>
                  <i style={{ width: `${cur / maxDur * 100}%` }} />
                  <b style={{ left: `${last / maxDur * 100}%` }} />
                </div>
                <span className="num" style={{ textAlign: 'right' }}>{duration(cur)}</span>
              </div>
            )
          })}
        </div>
        <div className="muted" style={{ fontSize: 14, marginTop: 10 }}>Bar = this week · line = last week</div>
      </div>

      {/* Recent activities */}
      <div className="card span-4">
        <div className="card-title">Recent activities</div>
        <ul className="recent">
          {a.recent.slice(0, 4).map(r => (
            <li key={r.id}>
              <button onClick={() => nav(`/session/${encodeURIComponent(r.id)}`)}>
                <SportIcon sport={r.sport} size={22} />
                <span className="stack" style={{ gap: 0, minWidth: 0 }}>
                  <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.name || TYPE_LABEL[r.session_type]}</span>
                  <span className="muted" style={{ fontSize: 14 }}>{when(r.start_time)} · {r.distance_m ? distance(r.distance_m, r.sport) : duration(r.duration_s)}</span>
                </span>
                <VerdictPill verdict={r.verdict} />
              </button>
            </li>
          ))}
        </ul>
      </div>

      {/* Training form (secondary) + validation */}
      <div className="span-3 stack" style={{ gap: 'var(--gap)' }}>
        <button className="card" onClick={() => nav(`/u/${u}/load`)}>
          <div className="card-title"><Gauge size={18} /> Training form</div>
          <div className="row"><span className="mid num" style={{ color: 'var(--form)' }}>{signed(a.form?.form, 0)}</span>
            <span className={`tone-${fs.tone}`} style={{ fontSize: 15 }}>{fs.label}</span></div>
          <div className="row muted" style={{ fontSize: 14 }}>
            <span>Fitness <b className="num" style={{ color: 'var(--fitness)' }}>{num(a.form?.fitness)}</b></span>
            <span>Fatigue <b className="num" style={{ color: 'var(--fatigue)' }}>{num(a.form?.fatigue)}</b></span>
          </div>
        </button>
        <button className="card" onClick={() => nav(`/u/${u}/validation`)}>
          <div className="card-title"><CheckCircle2 size={18} /> Verdict check</div>
          <div className="muted" style={{ fontSize: 15 }}>Do verdicts match how you felt?</div>
        </button>
      </div>
    </div>
  )
}
