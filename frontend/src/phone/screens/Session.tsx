import { ChevronRight } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api'
import { SportIcon, VerdictPill } from '../../components/icons'
import { SetList } from '../../components/SetList'
import { distance, duration, kmh, num, pace, SPORT_LABEL, TYPE_LABEL, when } from '../../format'
import { useFetch } from '../../useFetch'
import { factGroups, keyMetric, StreamChart } from '../../views/SessionDetail'
import { Back, Card } from '../parts'

/** All of a session's numbers, stacked for a phone: key numbers, the chart, laps, sets and the baseline. */
export function SessionScreen() {
  const { id } = useParams()
  const { data: s, error } = useFetch(() => api.session(id!), [id])
  if (error) return <><Back to="/" label="Today" /><Card>Could not load the session.</Card></>
  if (!s) return <div className="ph-boot">Loading…</div>
  const v = s.verdict
  const f = s.features || {}
  const laps = s.streams?.laps ?? []
  const numbers = factGroups(s)
  return (
    <div className="ph-stack">
      <div className="ph-row">
        {v ? <Back to={`/verdict/${encodeURIComponent(s.id)}`} label="Verdict" /> : <Back to="/" label="Today" />}
        {v && <span className="ph-right"><VerdictPill verdict={v.verdict} /></span>}
      </div>
      <section className="ph-section" style={{ gap: 4 }}>
        <span className="ph-label ph-row" style={{ gap: 6 }}><SportIcon sport={s.sport} size={16} />{SPORT_LABEL[s.sport]} · {TYPE_LABEL[s.session_type] ?? s.session_type}</span>
        <h1 className="ph-title">{s.name || SPORT_LABEL[s.sport]}</h1>
        <span className="ph-foot">{when(s.start_time)}{f.weather ? ` · ${num(f.weather.temp_c)} °C` : ''}{s.indoor ? ' · indoor' : ''}</span>
      </section>

      <div className="ph-grid3">
        {numbers.key.map(([k, val]) => (
          <div key={k} className="ph-card ph-stat sm"><span className="ph-label sm">{k}</span><b className="num">{val}</b></div>
        ))}
      </div>

      <div className="ph-chart"><StreamChart s={s} /></div>

      {numbers.groups.length > 0 && (
        <Card>
          {numbers.groups.map(g => (
            <div key={g.title} className="ph-dl">
              <span className="ph-label sm">{g.title}</span>
              <dl>{g.rows.map(([k, val]) => <div key={k}><dt>{k}</dt><dd className="num">{val}</dd></div>)}</dl>
            </div>
          ))}
        </Card>
      )}

      {laps.length > 0 && s.sport !== 'strength' && (
        <Card className="ph-flush">
          <span className="ph-label" style={{ padding: '0 16px' }}>Laps</span>
          <div className="table-wrap">
            <table className="data ph-table">
              <thead><tr><th>#</th><th className="num">Time</th><th className="num">Dist</th><th className="num">{s.sport === 'running' ? 'Pace' : s.sport === 'cycling' && s.has_power ? 'Power' : 'Speed'}</th><th className="num">HR</th></tr></thead>
              <tbody>
                {laps.map((l, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td><td className="num">{duration(l.duration_s)}</td><td className="num">{distance(l.distance_m, s.sport)}</td>
                    <td className="num">{s.sport === 'running' ? pace(l.avg_speed) : l.avg_power ? `${num(l.avg_power)} W` : kmh(l.avg_speed)}</td>
                    <td className="num">{num(l.avg_hr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {s.sets.length > 0 && (
        <Card>
          <span className="ph-label">Sets</span>
          <SetList sets={s.sets} exercises={f.exercises} />
        </Card>
      )}

      {s.baseline_sessions.length > 0 && (
        <Card>
          <span className="ph-label">Compared with</span>
          <span className="ph-foot">{s.baseline_sessions.length} similar sessions · key metric</span>
          {s.baseline_sessions.map(b => (
            <Link key={b.id} to={`/session/${encodeURIComponent(b.id)}`} className="ph-list-row">
              <div className="ph-grow"><span>{when(b.start_time)}</span>
                <span className="ph-foot num">{[distance(b.distance_m, s.sport), duration(b.duration_s), b.avg_hr ? `${num(b.avg_hr)} bpm` : null].filter(Boolean).join(' · ')}</span></div>
              <span className="num">{keyMetric(s.sport, b.features)}</span>
              <ChevronRight size={18} color="var(--faint)" aria-hidden />
            </Link>
          ))}
        </Card>
      )}
    </div>
  )
}
