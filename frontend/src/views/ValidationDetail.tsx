import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { VerdictPill } from '../components/icons'
import { feelLabel, num, SPORT_LABEL, when } from '../format'
import { useFetch } from '../useFetch'
import './Detail.css'

export function ValidationDetail() {
  const { user } = useParams()
  const nav = useNavigate()
  const { data } = useFetch(() => api.validation(user!), [user])
  if (!data) return <div className="muted">Loading…</div>
  const pct = data.agreement_pct
  const tone = pct == null ? 'muted' : pct >= 70 ? 'better' : pct >= 50 ? 'warn' : 'worse'
  const C = 2 * Math.PI * 88

  return (
    <div className="detail">
      <div className="label">Verdict check · last {data.days} days</div>
      <section className="card hero stripes">
        <div className="row" style={{ gap: 32, flexWrap: 'nowrap', alignItems: 'center' }}>
          <div className="big-ring" aria-label={pct == null ? 'No rated sessions yet' : `${pct}% agreement`}>
            <svg width="200" height="200" viewBox="0 0 200 200">
              <circle cx="100" cy="100" r="88" fill="none" stroke="var(--border)" strokeWidth="18" />
              {pct != null && <circle cx="100" cy="100" r="88" fill="none" stroke={`var(--${tone})`} strokeWidth="18" strokeLinecap="round"
                                      strokeDasharray={`${C * pct / 100} ${C}`} transform="rotate(-90 100 100)" />}
            </svg>
            <div><b>{pct == null ? '—' : `${pct}%`}</b><span className="label">Agreement</span></div>
          </div>
          <div className="stack" style={{ gap: 14 }}>
            <h1 className="display hero-title" style={{ fontSize: 'clamp(40px, calc(var(--vw) * 4.6), 58px)' }}>
              Do the verdicts match<br /><span className="hl">how you felt?</span>{' '}
              {pct == null ? '' : pct >= 70 ? 'Mostly, yes.' : pct >= 50 ? 'Partly.' : 'Not yet.'}
            </h1>
            <div className="row" style={{ gap: 10 }}>
              <div className="tile" style={{ minWidth: 150 }}><div className="label">Rated sessions</div><div className="v">{data.rated_sessions}</div></div>
              <div className="tile" style={{ minWidth: 150 }}><div className="label">Agree</div><div className="v tone-better">{data.agree}</div></div>
              <div className="tile" style={{ minWidth: 150 }}><div className="label">Disagree</div><div className="v tone-worse">{data.disagree}</div></div>
            </div>
          </div>
        </div>
      </section>

      <section className="card detail-grid" style={{ gap: 20 }}>
        {([['1 · Rate it', <>After each activity, rate <b>How did you feel</b> and <b>Perceived effort</b> on your watch or in Garmin Connect.</>],
           ['2 · We compare', <>“Better” on a day you felt strong — or “Worse” when you felt weak — counts as agreement.</>],
           ['3 · We tune', <>One bad day is normal. Low agreement over many sessions means the model needs tuning.</>]] as const).map(([t, d]) => (
          <div key={t} className="span-4">
            <div className="display" style={{ fontSize: 22, fontWeight: 800, color: 'var(--volt)' }}>{t}</div>
            <div style={{ color: 'var(--text-2)', lineHeight: 1.4 }}>{d}</div>
          </div>
        ))}
      </section>

      {data.flagged.length > 0 && (
        <div className="card">
          <div className="card-title">Disagreements to look at</div>
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>When</th><th>Sport</th><th>Verdict</th><th>You felt</th><th className="num">Effort</th></tr></thead>
              <tbody>
                {data.flagged.map(f => (
                  <tr key={f.id} className="clickable" onClick={() => nav(`/session/${encodeURIComponent(f.id)}`)}>
                    <td>{when(f.start_time)}</td><td>{SPORT_LABEL[f.sport]}</td><td><VerdictPill verdict={f.verdict} /></td>
                    <td>{feelLabel(f.feel)}</td><td className="num">{num(f.rpe)}/10</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
