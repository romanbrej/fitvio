import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Area, Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import type { HealthDay } from '../api'
import { hoursMinutes, num, shortDay } from '../format'
import { useFetch } from '../useFetch'
import './Detail.css'

interface MetricDef {
  title: string
  unit: string
  lowerBetter?: boolean
  lines: { key: keyof HealthDay; label: string; color: string; kind?: 'bar' | 'line' | 'area'; stack?: string }[]
  band?: [keyof HealthDay, keyof HealthDay]
  fmt?: (v: number) => string
}

const METRICS: Record<string, MetricDef> = {
  hrv: {
    title: 'Heart-rate variability', unit: 'ms',
    lines: [{ key: 'hrv_last_night', label: 'Last night', color: 'var(--primary)' },
            { key: 'hrv_weekly', label: '7-day avg', color: 'var(--form)' }],
    band: ['hrv_baseline_low', 'hrv_baseline_high'],
  },
  rhr: { title: 'Resting heart rate', unit: 'bpm', lowerBetter: true, lines: [{ key: 'rhr', label: 'Resting HR', color: 'var(--worse)' }] },
  sleep: {
    title: 'Sleep', unit: 'min', fmt: v => hoursMinutes(v),
    lines: [{ key: 'sleep_deep_min', label: 'Deep', color: '#6366f1', kind: 'bar', stack: 's' },
            { key: 'sleep_rem_min', label: 'REM', color: '#38bdf8', kind: 'bar', stack: 's' },
            { key: 'sleep_light_min', label: 'Light', color: '#475569', kind: 'bar', stack: 's' },
            { key: 'sleep_awake_min', label: 'Awake', color: '#f472b6', kind: 'bar', stack: 's' }],
  },
  body_battery: {
    title: 'Body Battery & stress', unit: '',
    lines: [{ key: 'bb_max', label: 'Body Battery max', color: 'var(--better)', kind: 'area' },
            { key: 'bb_min', label: 'Body Battery min', color: 'var(--muted)' },
            { key: 'stress_avg', label: 'Avg stress', color: 'var(--accent)' }],
  },
  vo2max: { title: 'VO₂max', unit: 'ml/kg/min', lines: [{ key: 'vo2max', label: 'VO₂max', color: 'var(--primary)' }] },
  steps: { title: 'Steps', unit: '', lines: [{ key: 'steps', label: 'Steps', color: 'var(--primary)', kind: 'bar' }] },
  weight: { title: 'Weight', unit: 'kg', lines: [{ key: 'weight_kg', label: 'Weight', color: 'var(--primary)' }] },
}

const RANGES = [30, 90, 180, 365]

export function HealthDetail() {
  const { user, metric } = useParams()
  const nav = useNavigate()
  const [days, setDays] = useState(90)
  const { data } = useFetch(() => api.health(user!, days), [user, days])
  const m = METRICS[metric ?? ''] ?? METRICS.hrv
  const rows = (data ?? []).map(d => ({
    ...d,
    band: m.band && d[m.band[0]] != null ? [d[m.band[0]], d[m.band[1]]] : null,
  }))
  const main = m.lines[0].key
  const vals = rows.map(r => r[main] as number | null).filter((v): v is number => v != null)
  const avg = (xs: number[]) => xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null
  const last7 = avg(vals.slice(-7))
  const prev28 = avg(vals.slice(-35, -7))
  const fmt = m.fmt ?? ((v: number) => `${num(v, v < 20 ? 1 : 0)}${m.unit ? ' ' + m.unit : ''}`)
  const diff = last7 != null && prev28 != null ? last7 - prev28 : null
  const good = diff == null ? null : m.lowerBetter ? diff < 0 : diff > 0

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="muted">Health</div>
          <h1>{m.title}</h1>
        </div>
        <div className="tabs">
          {RANGES.map(r => <button key={r} className="btn" aria-pressed={r === days} onClick={() => setDays(r)}>{r} days</button>)}
        </div>
      </div>
      <div className="tabs">
        {Object.entries(METRICS).map(([k, d]) => (
          <button key={k} className="btn" aria-pressed={k === metric} onClick={() => nav(`/u/${user}/health/${k}`, { replace: true })}>{d.title}</button>
        ))}
      </div>
      <div className="detail-grid">
        <div className="card span-12">
          <div className="kv" style={{ marginBottom: 12 }}>
            <div><div className="k">Latest</div><div className="v num">{vals.length ? fmt(vals[vals.length - 1]) : '—'}</div></div>
            <div><div className="k">7-day avg</div><div className="v num">{last7 != null ? fmt(last7) : '—'}</div></div>
            <div><div className="k">Previous 4 weeks</div><div className="v num">{prev28 != null ? fmt(prev28) : '—'}</div></div>
            <div><div className="k">Change</div>
              <div className={`v num ${good == null ? '' : Math.abs(diff!) < Math.abs(prev28! * 0.02) ? 'tone-inline' : good ? 'tone-better' : 'tone-worse'}`}>
                {diff == null ? '—' : `${diff > 0 ? '+' : '−'}${m.fmt ? m.fmt(Math.abs(diff)) : num(Math.abs(diff), 1)}`}
              </div></div>
          </div>
          <div className="chart-tall">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tickFormatter={shortDay} minTickGap={40} />
                <YAxis width={52} domain={['auto', 'auto']} tickFormatter={v => m.fmt ? m.fmt(v) : String(Math.round(v))} />
                <Tooltip labelFormatter={v => shortDay(String(v))} formatter={(v, k) => [Array.isArray(v) ? v.join('–') : (m.fmt ? m.fmt(Number(v)) : num(Number(v), 1)), String(k)]} />
                {m.band && <Area dataKey="band" stroke="none" fill="var(--better)" fillOpacity={0.12} name="Baseline range" isAnimationActive={false} />}
                {m.lines.map(l => l.kind === 'bar'
                  ? <Bar key={l.key} dataKey={l.key} fill={l.color} stackId={l.stack} name={l.label} isAnimationActive={false} />
                  : l.kind === 'area'
                    ? <Area key={l.key} dataKey={l.key} stroke={l.color} fill={l.color} fillOpacity={0.15} strokeWidth={2} name={l.label} isAnimationActive={false} connectNulls />
                    : <Line key={l.key} dataKey={l.key} stroke={l.color} strokeWidth={2} dot={metric === 'vo2max'} name={l.label} isAnimationActive={false} connectNulls />)}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="row muted" style={{ fontSize: 14 }}>
            {m.lines.map(l => <span key={l.key} className="row" style={{ gap: 6 }}><i style={{ width: 14, height: 4, background: l.color, display: 'inline-block', borderRadius: 2 }} />{l.label}</span>)}
            {m.band && <span>green band = your normal range</span>}
          </div>
        </div>
      </div>
    </div>
  )
}
