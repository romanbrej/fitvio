import { AlertTriangle, ChevronRight, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'
import type { Ambient, Delta, Session } from '../api'
import { SportIcon, VerdictIcon } from '../components/icons'
import { Sparkline } from '../components/Sparkline'
import { distance, duration, formState, kmh, num, pace, signed, SPORT_LABEL, TYPE_LABEL, VERDICT_LABEL, when } from '../format'
import './Wall.css'

export function deltaTone(d: Delta): string {
  if (d.z == null) return 'muted'
  return d.z >= 0.6 ? 'better' : d.z <= -0.6 ? 'worse' : 'inline'
}

function DeltaCard({ d, onClick }: { d: Delta; onClick: () => void }) {
  const tone = deltaTone(d)
  const shown = d.delta_fmt ?? '—'
  return (
    <button className="card delta" onClick={onClick}>
      <div className="card-title">{d.label}</div>
      <div className="delta-value num">{d.value_fmt}</div>
      <div className="delta-foot">
        <span className="muted">vs {d.baseline_fmt}{d.n ? ` · ${d.n} similar` : ''}</span>
        <span className={`pill tone-${tone}`}>{tone === 'better' ? '▲' : tone === 'worse' ? '▼' : '●'} {shown}</span>
      </div>
    </button>
  )
}

function facts(s: Session): [string, string][] {
  const f = s.features || {}
  const out: [string, string][] = [['Duration', duration(s.duration_s)]]
  if (s.distance_m) out.push(['Distance', distance(s.distance_m, s.sport)])
  if (s.sport === 'running' && f.avg_speed) out.push(['Avg pace', `${pace(f.avg_speed)} /km`])
  if (s.sport === 'cycling' && f.np) out.push(['Norm. power', `${num(f.np)} W`])
  else if (s.sport === 'cycling' && f.avg_speed) out.push(['Avg speed', `${kmh(f.avg_speed)} km/h`])
  if (s.sport === 'swimming' && f.swolf) out.push(['SWOLF', num(f.swolf)])
  if (s.sport === 'strength' && f.total_sets) out.push(['Sets', String(f.total_sets)], ['Volume', `${num(f.total_volume)} kg`])
  if (s.avg_hr) out.push(['Avg HR', `${num(s.avg_hr)} bpm`])
  out.push(['Load', num(s.load)])
  return out.slice(0, 5)
}

export function WallVerdict({ session, ambient: _ambient }: { session: Session; ambient: Ambient }) {
  const { dismiss, config } = useApp()
  const nav = useNavigate()
  const v = session.verdict!
  const t = v.trend
  const user = config.users.find(u => u.id === session.user_id)
  const open = () => nav(`/session/${encodeURIComponent(session.id)}`)
  const deltas = v.deltas.filter(d => d.value != null).slice(0, 4)
  const fs = formState(t.form_tomorrow)
  const trendPts = (t.trend_points ?? []).map(p => p.value)

  return (
    <div className="verdict-wall">
      <section className="verdict-hero">
        <div className="verdict-meta">
          <span className="sport-chip" style={{ borderColor: user?.color }}>
            <SportIcon sport={session.sport} size={22} />
            {SPORT_LABEL[session.sport]} · {TYPE_LABEL[session.session_type] ?? session.session_type}
          </span>
          <span className="muted">{when(session.start_time)}</span>
        </div>
        <h1 className="activity-name">{session.name || SPORT_LABEL[session.sport]}</h1>

        <button className={`verdict-big tone-${v.verdict}`} onClick={open} aria-label={`Verdict: ${VERDICT_LABEL[v.verdict]}. Open details`}>
          <VerdictIcon verdict={v.verdict} size={96} />
          <span>{VERDICT_LABEL[v.verdict]}</span>
        </button>
        <p className="headline">{v.headline}</p>
        <div className="confidence">
          <span className="pill">Confidence: {v.confidence}</span>
          {session.rpe != null && <span className="pill">RPE {num(session.rpe)}/10</span>}
        </div>

        <ul className="reasons">
          {v.reasons.slice(0, 4).map((r, i) => <li key={i}>{r}</li>)}
        </ul>
        {v.context.filter(c => c.kind !== 'rpe').length > 0 && (
          <div className="context">
            {v.context.filter(c => c.kind !== 'rpe').map((c, i) => (
              <span key={i} className="pill tone-warn"><AlertTriangle size={15} /> {c.text}</span>
            ))}
          </div>
        )}
      </section>

      <section className="verdict-side">
        {deltas.length > 0 && (
          <div className={`delta-grid ${deltas.length % 2 ? 'odd' : ''}`}>
            {deltas.map(d => <DeltaCard key={d.key} d={d} onClick={open} />)}
          </div>
        )}

        <button className="card facts" onClick={open}>
          {facts(session).map(([k, val]) => (
            <div key={k}><div className="fact-k">{k}</div><div className="fact-v num">{val}</div></div>
          ))}
        </button>

        <button className="card impact" onClick={() => nav(`/u/${session.user_id}/load`)}>
          <div className="card-title">Impact on your training</div>
          <div className="impact-row">
            <div>
              <div className="fact-k">Fitness</div>
              <div className="fact-v num" style={{ color: 'var(--fitness)' }}>{num(t.fitness_after)}</div>
              <div className="muted num">{signed(t.fitness_after - t.fitness_before, 1)}</div>
            </div>
            <div>
              <div className="fact-k">Fatigue</div>
              <div className="fact-v num" style={{ color: 'var(--fatigue)' }}>{num(t.fatigue_after)}</div>
              <div className="muted num">{signed(t.fatigue_after - t.fatigue_before, 1)}</div>
            </div>
            <div>
              <div className="fact-k">Form tomorrow</div>
              <div className="fact-v num" style={{ color: 'var(--form)' }}>{signed(t.form_tomorrow, 0)}</div>
              <div className={`tone-${fs.tone}`}>{fs.label}</div>
            </div>
            {t.trend_metric && (
              <div className="impact-trend">
                <div className="fact-k">{t.trend_metric}, 6 weeks</div>
                <Sparkline values={trendPts} />
                <div className={t.trend_pct_per_week == null ? 'muted' : t.trend_pct_per_week > 0.2 ? 'tone-better' : t.trend_pct_per_week < -0.2 ? 'tone-worse' : 'tone-inline'}>
                  {t.trend_pct_per_week == null ? 'Not enough data' : `${signed(t.trend_pct_per_week, 1, '%')} per week`}
                </div>
              </div>
            )}
          </div>
        </button>

        <div className="verdict-actions">
          <button className="btn" onClick={open}>All details <ChevronRight size={20} /></button>
          <button className="btn" onClick={() => dismiss(session.id)}><X size={20} /> Overview</button>
        </div>
      </section>
    </div>
  )
}
