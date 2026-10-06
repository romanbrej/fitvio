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
    lines: [{ key: 'hrv_last_night', label: 'Last night', color: 'var(--fitness)' },
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
  vo2max: {
    title: 'VO₂max', unit: 'ml/kg/min', fmt: v => v.toFixed(1),  // Garmin's precise value, e.g. 44.1
    lines: [{ key: 'vo2max', label: 'Running', color: 'var(--volt)' },
            { key: 'vo2max_cycling', label: 'Cycling', color: 'var(--accent)' }],
  },
  steps: { title: 'Steps', unit: '', lines: [{ key: 'steps', label: 'Steps', color: 'var(--fitness)', kind: 'bar' }] },
  weight: { title: 'Weight', unit: 'kg', lines: [{ key: 'weight_kg', label: 'Weight', color: 'var(--fitness)' }] },
}

const RANGES = [30, 90, 180, 365]
const TAB: Record<string, string> = { hrv: 'HRV', rhr: 'Resting HR', body_battery: 'Body Battery & stress' }

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
  const flat = diff != null && prev28 != null && Math.abs(diff) < Math.abs(prev28 * 0.02)

  return (
    <div className="detail">
      <div className="between" style={{ flexWrap: 'wrap' }}>
        <div className="tabs">
          {Object.entries(METRICS).map(([k, d]) => (
            <button key={k} className="btn" aria-pressed={k === metric} onClick={() => nav(`/u/${user}/health/${k}`, { replace: true })}>{TAB[k] ?? d.title}</button>
          ))}
        </div>
        <div className="segmented">
          {RANGES.map(r => <button key={r} className="btn" aria-pressed={r === days} onClick={() => setDays(r)}>{r} d</button>)}
        </div>
      </div>
      <section className="card hero stripes">
        <div className="hero-grid">
          <div className="stack" style={{ gap: 6 }}>
            <div className="label">{m.title}</div>
            <h1 className="display hero-title" style={{ fontSize: 'clamp(44px, calc(var(--vw) * 5), 64px)' }}>
              {good == null ? 'Building your baseline.' : flat ? <>Holding <span className="hl">steady.</span></>
                : good ? <>Trending the <span className="hl">right way.</span></> : <>Worth <span style={{ color: 'var(--warn)' }}>watching.</span></>}
            </h1>
            <div className="hero-sub">Last 7 days vs. the 4 weeks before{m.lowerBetter ? ' — lower is better' : ''}.</div>
          </div>
          <div className="kpi-grid four">
            <div className="tile"><div className="label">Latest</div><div className="v">{vals.length ? fmt(vals[vals.length - 1]) : '—'}</div></div>
            <div className="tile"><div className="label">7-day avg</div><div className="v">{last7 != null ? fmt(last7) : '—'}</div></div>
            <div className="tile"><div className="label">Prev 4 weeks</div><div className="v muted">{prev28 != null ? fmt(prev28) : '—'}</div></div>
            <div className="tile"><div className="label">Change</div>
              <div className={`v ${good == null ? '' : flat ? 'tone-inline' : good ? 'tone-better' : 'tone-worse'}`}>
                {diff == null ? '—' : `${diff > 0 ? '+' : '−'}${m.fmt ? m.fmt(Math.abs(diff)) : num(Math.abs(diff), 1)}`}
              </div></div>
          </div>
        </div>
      </section>
      <div className="detail-grid">
        <div className="card span-12">
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
