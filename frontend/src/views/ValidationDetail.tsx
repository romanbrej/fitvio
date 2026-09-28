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

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="muted">Verdict check · last {data.days} days</div>
          <h1>Do the verdicts match how you felt?</h1>
        </div>
      </div>
      <div className="detail-grid">
        <div className="card span-12">
          <div className="kv">
            <div><div className="k">Agreement</div><div className={`v num ${pct == null ? '' : pct >= 70 ? 'tone-better' : pct >= 50 ? 'tone-warn' : 'tone-worse'}`}>{pct == null ? '—' : `${pct}%`}</div></div>
            <div><div className="k">Rated sessions</div><div className="v num">{data.rated_sessions}</div></div>
            <div><div className="k">Agree</div><div className="v num">{data.agree}</div></div>
            <div><div className="k">Disagree</div><div className="v num">{data.disagree}</div></div>
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>
            After each activity, rate <b>How did you feel</b> and <b>Perceived effort</b> on your watch or in Garmin Connect.
            A "Better" verdict on a day you felt strong (or "Worse" when you felt weak) counts as agreement.
            A single bad day is normal — a low agreement over many sessions means the model needs tuning.
          </p>
        </div>
        {data.flagged.length > 0 && (
          <div className="card span-12">
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
    </div>
  )
}
