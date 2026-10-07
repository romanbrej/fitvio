import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, Line, ComposedChart } from 'recharts'
import { api } from '../api'
import type { Sport, VerdictKind } from '../api'
import { SportIcon, VerdictPill } from '../components/icons'
import { distance, duration, num, pace, shortDay, SPORT_LABEL, TYPE_LABEL, VERDICT_LABEL, when } from '../format'
import { useFetch } from '../useFetch'
import './Detail.css'

const PRIMARY: Record<string, { label: string; get: (f: Record<string, any>) => number | null | undefined; fmt: (v: number) => string }> = {
  // pace held at the reference HR in s/km (grade & heat adjusted, so runs compare fairly) — lower is faster
  running: { label: 'Pace at fixed HR (/km, grade & heat adjusted) — steady time at that HR in any run, lower is faster',
             get: f => { const v = f.speed_at_ref_hr_adj ?? f.speed_at_ref_hr; return v ? 1000 / v : null }, fmt: v => duration(v) },
  cycling: { label: 'Power per heartbeat (W/beat)', get: f => f.ef, fmt: v => v.toFixed(2) },
  swimming: { label: 'Pace per 100 m (s) — lower is better', get: f => f.pace_100m_s, fmt: v => duration(v) },
  strength: { label: 'Session volume (kg)', get: f => f.total_volume, fmt: v => num(v) },
  other: { label: 'Training load', get: () => null, fmt: v => num(v) },
}

const VCOLOR: Record<VerdictKind, string> = {
  better: 'var(--better)', in_line: 'var(--inline)', worse: 'var(--worse)', not_comparable: 'var(--na)', load_only: 'var(--load)',
}

export function SportDetail() {
  const { user, sport } = useParams()
  const nav = useNavigate()
  const { data } = useFetch(() => api.sessions(user!, sport, 200), [user, sport])
  const p = PRIMARY[sport ?? 'other'] ?? PRIMARY.other
  const [all, setAll] = useState(false)
  // running: like the wall card, every outdoor run with steady time at the reference HR (others have no value)
  const usable = (s: { indoor?: boolean | number; features?: Record<string, any> | null }) => sport !== 'running' || !s.indoor
  const pts = (data ?? []).filter(usable).slice().reverse()
    .map(s => ({ t: new Date(s.start_time).getTime(), v: p.get(s.features ?? {}), verdict: s.verdict, id: s.id, type: s.session_type }))
    .filter(x => x.v != null)
  // 5-session rolling median as the trend line
  const withTrend = pts.map((x, i) => {
    const win = pts.slice(Math.max(0, i - 4), i + 1).map(y => y.v as number).sort((a, b) => a - b)
    return { ...x, trend: win[Math.floor(win.length / 2)] }
  })

  // the hero's answer: trend now vs. the start of the shown history
  const lowerBetter = sport === 'running' || sport === 'swimming'
  let answer: { word: string; text: string; now: number; then: number; best: number; weeks: number } | null = null
  if (withTrend.length >= 4) {
    // like the wall: now vs. about 6 weeks ago (the trend point closest to 42 days before the last one)
    const lastPt = withTrend[withTrend.length - 1]
    const ref = [...withTrend].reverse().find(x => lastPt.t - x.t >= 42 * 86400000) ?? withTrend[Math.min(4, withTrend.length - 1)]
    const first = ref.trend
    const last = lastPt.trend
    const recent = withTrend.filter(x => lastPt.t - x.t <= 365 * 86400000).map(x => x.v as number)
    const best = lowerBetter ? Math.min(...recent) : Math.max(...recent)
    const weeks = Math.max(1, Math.round((lastPt.t - ref.t) / 604800000))
    const gain = lowerBetter ? first - last : last - first
    const rel = Math.abs(gain) / Math.abs(first || 1)
    const unit = sport === 'running' ? `${Math.round(Math.abs(gain))} s/km` : sport === 'swimming' ? `${Math.round(Math.abs(gain))} s/100 m`
      : `${(rel * 100).toFixed(1)} %`
    const word = rel < 0.01 ? 'Holding.' : gain > 0 ? 'Yes.' : 'Not yet.'
    const text = rel < 0.01 ? `Steady over ${weeks} weeks.`
      : `${unit} ${gain > 0 ? (lowerBetter ? 'faster' : 'better') : (lowerBetter ? 'slower' : 'lower')} in ${weeks} weeks.`
    answer = { word, text, now: last, then: first, best, weeks }
  }
  // running: cadence of the easy and long runs (same runs as the pace chart)
  const cadence = sport === 'running' ? pts.map(x => {
    const s = (data ?? []).find(d => d.id === x.id)
    const c = s?.features?.avg_cadence
    return c ? { t: x.t, spm: c < 120 ? c * 2 : c } : null
  }).filter((x): x is { t: number; spm: number } => x != null) : []

  // strength: per-exercise e1RM history
  const exHist: Record<string, { label: string; pts: { t: number; v: number }[] }> = {}
  if (sport === 'strength') {
    (data ?? []).slice().reverse().forEach(s => {
      Object.entries((s.features?.exercises ?? {}) as Record<string, any>).forEach(([k, e]) => {
        if (!e.e1rm) return
        ;(exHist[k] ??= { label: e.label ?? k, pts: [] }).pts.push({ t: new Date(s.start_time).getTime(), v: e.e1rm })
      })
    })
  }

  return (
    <div className="detail">
      <nav className="tabs" aria-label="Sport">
        {(['running', 'cycling', 'swimming', 'strength'] as Sport[]).map(sp => (
          <button key={sp} className="btn" aria-pressed={sp === sport} onClick={() => nav(`/u/${user}/sport/${sp}`, { replace: true })}>
            <SportIcon sport={sp} size={18} /> {SPORT_LABEL[sp]}
          </button>
        ))}
      </nav>
      <section className="card hero stripes">
        <div className="hero-grid">
          <div className="stack" style={{ gap: 6 }}>
            <div className="label">Am I improving?</div>
            <h1 className="display hero-title">
              {answer ? <><span className="hl">{answer.word}</span> {answer.text}</> : 'Not enough sessions yet.'}
            </h1>
          </div>
          {answer && (
            <div className="kpi-grid">
              <div className="tile"><div className="label">Now (trend)</div><div className="v" style={{ color: 'var(--volt)' }}>{p.fmt(answer.now)}</div></div>
              <div className="tile"><div className="label">{answer.weeks} weeks ago</div><div className="v">{p.fmt(answer.then)}</div></div>
              <div className="tile"><div className="label">Best · 12 mo</div><div className="v" style={{ color: 'var(--accent-2)' }}>{p.fmt(answer.best)}</div></div>
              <div className="tile"><div className="label">Sessions</div><div className="v">{pts.length}</div></div>
            </div>
          )}
        </div>
      </section>
      <div className="detail-grid">
        {pts.length > 1 && sport !== 'strength' && (
          <div className="card span-12">
            <div className="card-title">{p.label}</div>
            <div className="chart-tall">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={withTrend} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} scale="time" tickFormatter={v => shortDay(new Date(v).toISOString())} minTickGap={40} />
                  <YAxis width={52} domain={['auto', 'auto']} reversed={sport === 'swimming' || sport === 'running'} tickFormatter={p.fmt} />
                  <Tooltip labelFormatter={v => shortDay(new Date(Number(v)).toISOString())} formatter={(v, k) => [p.fmt(Number(v)), k === 'trend' ? 'Trend (5-session median)' : 'Session']} />
                  <Line dataKey="trend" stroke="var(--volt)" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                  <Scatter dataKey="v" isAnimationActive={false} onClick={(d: any) => d?.payload?.id && nav(`/session/${encodeURIComponent(d.payload.id)}`)}
                           shape={(props: any) => <circle cx={props.cx} cy={props.cy} r={6} fill={VCOLOR[props.payload.verdict as VerdictKind] ?? 'var(--na)'} style={{ cursor: 'pointer' }} />} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="row muted" style={{ fontSize: 14 }}>
              Dots = sessions, coloured by verdict ({(['better', 'in_line', 'worse', 'not_comparable'] as VerdictKind[]).map(k => <span key={k} style={{ color: VCOLOR[k] }}>● {VERDICT_LABEL[k]} </span>)}) · line = 5-session median · tap a dot to open it
            </div>
          </div>
        )}

        {cadence.length > 1 && (
          <div className="card span-12">
            <div className="card-title">Cadence · easy &amp; long runs (steps per minute)</div>
            <div className="chart">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={cadence} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} scale="time" tickFormatter={v => shortDay(new Date(v).toISOString())} minTickGap={40} />
                  <YAxis width={52} domain={['dataMin - 4', 'dataMax + 4']} tickFormatter={v => String(Math.round(v))} />
                  <Tooltip labelFormatter={v => shortDay(new Date(Number(v)).toISOString())} formatter={v => [`${Math.round(Number(v))} spm`, 'Cadence']} />
                  <Line dataKey="spm" stroke="var(--run)" strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="muted" style={{ fontSize: 14 }}>Information only — the right cadence depends on your pace, so it never counts toward a verdict.</div>
          </div>
        )}

        {Object.keys(exHist).length > 0 && (
          <div className="card span-12">
            <div className="card-title">Estimated 1-rep max per exercise</div>
            <div className="chart-tall">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} scale="time" tickFormatter={v => shortDay(new Date(v).toISOString())} minTickGap={40} />
                  <YAxis dataKey="v" width={52} domain={['auto', 'auto']} unit=" kg" />
                  <Tooltip formatter={v => [`${num(Number(v), 1)} kg`]} labelFormatter={() => ''} />
                  {Object.entries(exHist).map(([k, e], i) => (
                    <Scatter key={k} name={e.label} data={e.pts} line lineType="joint" isAnimationActive={false}
                             fill={['#60a5fa', '#f97316', '#22c55e', '#f472b6', '#facc15', '#a78bfa'][i % 6]} />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <div className="row muted" style={{ fontSize: 14 }}>
              {Object.values(exHist).map((e, i) => <span key={e.label + i} style={{ color: ['#60a5fa', '#f97316', '#22c55e', '#f472b6', '#facc15', '#a78bfa'][i % 6] }}>● {e.label}</span>)}
            </div>
          </div>
        )}

        <div className="card span-12">
          <div className="card-title">Sessions</div>
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>When</th><th>Session</th><th>Type</th><th className="num">Duration</th><th className="num">Distance</th>{sport === 'running' && <th className="num">Pace</th>}<th className="num">Key metric</th><th>Verdict</th></tr></thead>
              <tbody>
                {(data ?? []).slice(0, all ? undefined : 30).map(s => {
                  const v = p.get(s.features ?? {})
                  return (
                    <tr key={s.id} className="clickable" onClick={() => nav(`/session/${encodeURIComponent(s.id)}`)}>
                      <td>{when(s.start_time)}</td><td>{s.name ?? '—'}</td><td>{TYPE_LABEL[s.session_type] ?? s.session_type}</td>
                      <td className="num">{duration(s.duration_s)}</td><td className="num">{distance(s.distance_m, s.sport)}</td>
                      {sport === 'running' && <td className="num">{pace(s.features?.avg_speed)}</td>}
                      <td className="num">{v != null ? p.fmt(v) : '—'}</td>
                      <td><VerdictPill verdict={s.verdict as VerdictKind | null} /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {!all && (data?.length ?? 0) > 30 && (
            <button className="btn" style={{ marginTop: 12 }} onClick={() => setAll(true)}>Show all {data!.length}</button>
          )}
        </div>
      </div>
    </div>
  )
}
