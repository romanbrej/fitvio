import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Area, Bar, CartesianGrid, ComposedChart, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { formState, num, shortDay, signed } from '../format'
import { useFetch } from '../useFetch'
import './Detail.css'

const RANGES = [42, 90, 180, 365]

export function LoadDetail() {
  const { user } = useParams()
  const [days, setDays] = useState(90)
  const { data } = useFetch(() => api.pmc(user!, days), [user, days])
  const { data: prof } = useFetch(() => api.profile(user!), [user])
  const last = data?.at(-1)
  const fs = formState(last?.form)

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="muted">Training load</div>
          <h1>Fitness, fatigue & form</h1>
        </div>
        <div className="tabs">
          {RANGES.map(r => <button key={r} className="btn" aria-pressed={r === days} onClick={() => setDays(r)}>{r} days</button>)}
        </div>
      </div>
      <div className="detail-grid">
        <div className="card span-12">
          <div className="kv" style={{ marginBottom: 12 }}>
            <div><div className="k">Fitness (42-day)</div><div className="v num" style={{ color: 'var(--fitness)' }}>{num(last?.fitness, 1)}</div></div>
            <div><div className="k">Fatigue (7-day)</div><div className="v num" style={{ color: 'var(--fatigue)' }}>{num(last?.fatigue, 1)}</div></div>
            <div><div className="k">Form</div><div className="v num" style={{ color: 'var(--form)' }}>{signed(last?.form, 0)}</div><div className={`tone-${fs.tone}`} style={{ fontSize: 15 }}>{fs.label}</div></div>
          </div>
          <div className="chart-tall">
            {data && (
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="day" tickFormatter={shortDay} minTickGap={40} />
                  <YAxis yAxisId="l" width={44} />
                  <YAxis yAxisId="load" orientation="right" width={44} />
                  <ReferenceArea yAxisId="l" y1={-30} y2={-10} fill="var(--better)" fillOpacity={0.06} />
                  <Tooltip labelFormatter={v => shortDay(String(v))} formatter={(v, k) => [num(Number(v), 1), String(k)]} />
                  <Bar yAxisId="load" dataKey="load" fill="var(--surface-2)" isAnimationActive={false} name="Daily load" />
                  <Area yAxisId="l" type="monotone" dataKey="fitness" stroke="var(--fitness)" fill="var(--fitness)" fillOpacity={0.12} strokeWidth={2.5} isAnimationActive={false} name="Fitness" />
                  <Line yAxisId="l" type="monotone" dataKey="fatigue" stroke="var(--fatigue)" strokeDasharray="5 4" dot={false} strokeWidth={2} isAnimationActive={false} name="Fatigue" />
                  <Line yAxisId="l" type="monotone" dataKey="form" stroke="var(--form)" dot={false} strokeWidth={2} isAnimationActive={false} name="Form" />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="muted" style={{ fontSize: 14 }}>
            Blue area = fitness · pink dashed = fatigue · yellow = form · grey bars = daily load (right axis) · green band = productive training zone (form −10 to −30)
          </div>
        </div>
        {prof && (
          <div className="card span-12">
            <div className="card-title">Your heart-rate profile — read from Garmin</div>
            <div className="kv">
              {([['max_hr', 'Max HR', ' bpm'], ['rest_hr', 'Resting HR', ' bpm'], ['lthr', 'Threshold HR', ' bpm'], ['ftp', 'FTP', ' W'], ['sex', 'Sex', '']] as const).map(([k, label, unit]) => (
                <div key={k}>
                  <div className="k">{label}</div>
                  <div className="v num">{prof[k].value == null ? '—' : typeof prof[k].value === 'number' ? `${Math.round(prof[k].value as number)}${unit}` : String(prof[k].value)}</div>
                  <div className="faint" style={{ fontSize: 13 }}>{prof[k].source}</div>
                </div>
              ))}
            </div>
            <p className="muted" style={{ margin: '12px 0 0', fontSize: 15 }}>
              Zones, session types and training load are computed from these values. They update on every sync;
              if they change, your whole history is recalculated.
            </p>
          </div>
        )}
        <div className="card span-12">
          <div className="card-title">How to read this</div>
          <p style={{ margin: 0 }}>
            Every activity adds training load (heart-rate based, so all sports count on the same scale).
            <b> Fitness</b> is your 42-day average load: it rises slowly and is what you are building.
            <b> Fatigue</b> is the 7-day average: it reacts fast. <b>Form</b> = fitness − fatigue.
            Negative form while fitness rises means you are training productively; very negative form for long is a warning sign.
          </p>
        </div>
      </div>
    </div>
  )
}
