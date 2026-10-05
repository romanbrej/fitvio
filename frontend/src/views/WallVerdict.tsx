import { AlertTriangle, ChevronRight, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'
import type { Ambient, Delta, Session } from '../api'
import { Buddy } from '../components/Buddy'
import { SportIcon, VerdictIcon } from '../components/icons'
import { Improvements } from '../components/Improvements'
import { distance, duration, kmh, num, pace, SPORT_LABEL, TYPE_LABEL, VERDICT_LABEL, when } from '../format'
import './Wall.css'

export function deltaTone(d: Delta): string {
  if (d.z == null) return 'muted'
  return d.z >= 0.6 ? 'better' : d.z <= -0.6 ? 'worse' : 'inline'
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
  if (s.sport === 'running' && f.avg_cadence) out.push(['Cadence', `${num(f.avg_cadence * (f.avg_cadence < 120 ? 2 : 1))} spm`])
  out.push(['Load', `${num(s.load)}`])
  return out.slice(0, 6)
}

export function WallVerdict({ session, ambient }: { session: Session; ambient: Ambient }) {
  const { dismiss, config } = useApp()
  const nav = useNavigate()
  const v = session.verdict!
  const user = config.users.find(u => u.id === session.user_id)
  const open = () => nav(`/session/${encodeURIComponent(session.id)}`)

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
        <div className="verdict-title-row">
          <div style={{ minWidth: 0 }}>
            <div className="verdict-kicker">Session complete</div>
            <h1 className="activity-name">{session.name || SPORT_LABEL[session.sport]}</h1>
          </div>
          {ambient.buddy && (
            <div className="verdict-buddy">
              <Buddy animal={ambient.buddy.animal} mood={v.verdict === 'better' ? 'overjoyed' : 'content'} size={96} pettable />
            </div>
          )}
        </div>

        <button className={`verdict-big tone-${v.verdict}`} onClick={open} aria-label={`Verdict: ${VERDICT_LABEL[v.verdict]}. Open details`}>
          <VerdictIcon verdict={v.verdict} size={72} strokeWidth={3} />
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
        <Improvements items={session.improvements ?? []}
                      onClick={() => nav(`/u/${session.user_id}/load`)} />

        <button className="card facts" onClick={open}>
          {facts(session).map(([k, val]) => (
            <div key={k}><div className="fact-k">{k}</div><div className="fact-v num">{val}</div></div>
          ))}
        </button>

        <div className="verdict-actions">
          <button className="btn primary" onClick={open}>All details <ChevronRight size={20} /></button>
          <button className="btn" onClick={() => dismiss(session.id)}><X size={20} /> Overview</button>
        </div>
      </section>
    </div>
  )
}
