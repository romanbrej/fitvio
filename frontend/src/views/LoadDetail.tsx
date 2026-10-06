import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Area, Bar, CartesianGrid, ComposedChart, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { formState, num, shortDay, signed } from '../format'
import { useFetch } from '../useFetch'
import './Detail.css'

const RANGES = [42, 90, 180, 365]
// the same bands as formState()
const BANDS = [
  { label: 'Overreaching', range: 'below −30', lo: -Infinity, hi: -30, w: 20, c: '#7f1d1d' },
  { label: 'Productive', range: '−30 to −10', lo: -30, hi: -10, w: 20, c: 'rgba(61,220,132,.75)' },
  { label: 'Neutral', range: '−10 to +5', lo: -10, hi: 5, w: 15, c: 'rgba(56,189,248,.6)' },
  { label: 'Fresh', range: '+5 to +25', lo: 5, hi: 25, w: 20, c: 'rgba(250,204,21,.8)' },
  { label: 'Losing fitness', range: 'above +25', lo: 25, hi: Infinity, w: 15, c: '#64748b' },
]

export function LoadDetail() {
  const { user } = useParams()
  const [days, setDays] = useState(90)
  const { data } = useFetch(() => api.pmc(user!, days), [user, days])
  const { data: prof } = useFetch(() => api.profile(user!), [user])
  const last = data?.at(-1)
  const fs = formState(last?.form)
  const firstDay = data?.[0]
  const gain = last && firstDay ? last.fitness - firstDay.fitness : null
  const since = firstDay ? new Date(firstDay.day).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''

  return (
    <div className="detail">
      <div className="between" style={{ flexWrap: 'wrap' }}>
        <div className="label">Training load · fitness, fatigue &amp; form (TRIMP)</div>
        <div className="segmented">
          {RANGES.map(r => <button key={r} className="btn" aria-pressed={r === days} onClick={() => setDays(r)}>{r} d</button>)}
        </div>
      </div>
      <section className="card hero stripes">
        <div className="hero-grid">
          <h1 className="display hero-title" style={{ fontSize: 'clamp(44px, calc(var(--vw) * 5.2), 66px)' }}>
            {gain == null ? 'Your training load.' : Math.abs(gain) < 1 ? <>Fitness holding.<br /><span className="hl">Keep it steady.</span></>
              : gain > 0 ? <>Fitness +{gain.toFixed(0)} since {since}.<br /><span className="hl">You’re building.</span></>
              : <>Fitness {gain.toFixed(0)} since {since}.<br /><span style={{ color: 'var(--warn)' }}>Time to rebuild.</span></>}
          </h1>
          <div className="row" style={{ gap: 12, flexWrap: 'nowrap' }}>
            <div className="tile"><div className="label">Fitness · 42 d</div><div className="v" style={{ fontSize: 36, color: 'var(--fitness)' }}>{num(last?.fitness, 1)}</div></div>
            <div className="tile"><div className="label">Fatigue · 7 d</div><div className="v" style={{ fontSize: 36, color: 'var(--fatigue)' }}>{num(last?.fatigue, 1)}</div></div>
            <div className="tile"><div className="label">Form</div><div className="v" style={{ fontSize: 36, color: 'var(--form)' }}>{signed(last?.form, 0)}</div>
              <div className={`small strong tone-${fs.tone}`}>{fs.label}</div></div>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-title">Where your form is</div>
        <div className="form-scale">
          <div className="form-scale-bar" style={{ gridTemplateColumns: BANDS.map(b => `${b.w}fr`).join(' ') }}>
            {BANDS.map(b => <i key={b.label} style={{ background: b.c }} />)}
          </div>
          {last && <span className="form-scale-mark" style={{ left: `${(Math.max(-50, Math.min(40, last.form)) + 50) / 90 * 100}%` }} />}
        </div>
        <div className="form-scale-labels" style={{ gridTemplateColumns: BANDS.map(b => `${b.w}fr`).join(' ') }}>
          {BANDS.map(b => <span key={b.label} className={last && last.form > b.lo && last.form <= b.hi ? 'on' : ''}>{b.label}<br />{b.range}</span>)}
        </div>
      </section>

      <div className="detail-grid">
        <div className="card span-12">
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
            <div className="card-title">Your heart-rate profile · from Garmin</div>
            <div className="kv">
              {([['max_hr', 'Max HR', ' bpm'], ['rest_hr', 'Resting HR', ' bpm'], ['lthr', 'Threshold HR', ' bpm'], ['ftp', 'FTP', ' W'], ['weight_kg', 'Weight', ' kg'], ['sex', 'Sex', '']] as const).map(([k, label, unit]) => (
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
        {([['Fitness', 'var(--fitness)', 'Your 42-day average load. It rises slowly — this is what you are building.'],
           ['Fatigue', 'var(--fatigue)', 'Your 7-day average load. It reacts fast to hard days and drops on rest days.'],
           ['Form', 'var(--form)', 'Fitness minus fatigue, including today. Negative while fitness rises = productive. Positive = fresh, ready to race.']] as const).map(([t, c, d]) => (
          <div key={t} className="card span-4 explain" style={{ '--c': c } as React.CSSProperties}>
            <div className="display">{t}</div>
            <p style={{ margin: '4px 0 0', color: 'var(--text-2)', lineHeight: 1.4 }}>{d}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
