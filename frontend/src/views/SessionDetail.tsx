import { AlertTriangle } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Bar, BarChart } from 'recharts'
import { api } from '../api'
import type { Delta, SessionDetail } from '../api'
import { SportIcon, VerdictPill } from '../components/icons'
import { Improvements } from '../components/Improvements'
import { distance, duration, feelLabel, kmh, num, pace, SPORT_LABEL, TYPE_LABEL, when } from '../format'
import { useFetch } from '../useFetch'
import { deltaTone } from './WallVerdict'
import './Detail.css'

function ZBar({ z }: { z: number | null }) {
  if (z == null) return <span className="faint">—</span>
  const w = Math.min(Math.abs(z), 3) / 3 * 50
  const color = z >= 0.6 ? 'var(--better)' : z <= -0.6 ? 'var(--worse)' : 'var(--inline)'
  return <div className="zbar" aria-label={`score ${z}`}><i style={{ left: z >= 0 ? '50%' : `${50 - w}%`, width: `${w}%`, background: color }} /></div>
}

function DeltaTable({ deltas }: { deltas: Delta[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr><th>Metric</th><th className="num">This session</th><th className="num">Your baseline</th><th className="num">Change</th><th>vs. normal spread</th><th className="num">n</th></tr></thead>
        <tbody>
          {deltas.map(d => (
            <tr key={d.key}>
              <td>{d.label}</td>
              <td className="num">{d.value_fmt}</td>
              <td className="num muted">{d.baseline_fmt}</td>
              <td className={`num tone-${deltaTone(d)}`}>{d.delta_fmt ?? '—'}</td>
              <td><ZBar z={d.z} /></td>
              <td className="num muted">{d.n}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function facts(s: SessionDetail): [string, string][] {
  const f = s.features || {}
  const out: [string, string][] = [
    ['Duration', duration(s.duration_s)], ['Distance', distance(s.distance_m, s.sport)],
    ['Avg HR', s.avg_hr ? `${num(s.avg_hr)} bpm` : '—'], ['Max HR', s.max_hr ? `${num(s.max_hr)} bpm` : '—'],
    ['Training load', num(s.load)],
  ]
  if (s.ascent_m) out.push(['Ascent', `${num(s.ascent_m)} m`])
  // Garmin's weather for this activity (station near the start) — not the wrist sensor
  const w = f.weather
  if (w) {
    out.push(['Weather', `${num(w.temp_c)} °C${w.desc ? ` · ${w.desc}` : ''}`])
    if (w.feels_like_c != null) out.push(['Feels like', `${num(w.feels_like_c)} °C`])
    if (w.humidity != null) out.push(['Humidity', `${num(w.humidity)} %${w.dew_point_c != null ? ` · dew pt ${num(w.dew_point_c)} °C` : ''}`])
    if (w.wind_kmh != null) out.push(['Wind', `${num(w.wind_kmh)} km/h${w.wind_dir ? ` ${w.wind_dir}` : ''}`])
    if (w.station) out.push(['Weather station', w.station])
  }
  if (f.heat_acclimation != null) out.push(['Heat acclimation', `${num(f.heat_acclimation)} %`])
  if (f.heat_adj_pct) out.push(['Heat adjustment', `+${num(f.heat_adj_pct, 1)} % efficiency`])
  if (s.sport === 'running') {
    out.push(['Avg pace', `${pace(f.avg_speed)} /km`], ['Grade-adj. pace', `${pace(f.gap_speed)} /km`],
      ['Efficiency', num(f.ef_adj, 2)], ['HR drift', f.decoupling != null ? `${num(f.decoupling, 1)} %` : '—'],
      [`Pace @ ${f.ref_hr ?? ''} bpm`, f.speed_at_ref_hr ? `${pace(f.speed_at_ref_hr)} /km` : '—'],
      ['Cadence', f.avg_cadence ? `${num(f.avg_cadence * (f.avg_cadence < 120 ? 2 : 1))} spm` : '—'])
    if (f.work_speed) out.push(['Reps', num(f.rep_count)], ['Rep pace', `${pace(f.work_speed)} /km`],
      ['Rep HR', `${num(f.work_hr)} bpm`], ['HR drop between reps', `${num(f.hr_recovery)} bpm`])
  }
  if (s.sport === 'cycling') {
    if (f.avg_power) out.push(['Avg power', `${num(f.avg_power)} W`], ['Norm. power', `${num(f.np)} W`],
      ['W / beat', num(f.ef, 2)], ['Intensity factor', num(f.intensity_factor, 2)], ['eFTP', f.eftp ? `${num(f.eftp)} W` : '—'])
    else out.push(['Avg speed', `${kmh(f.avg_speed)} km/h`])
  }
  if (s.sport === 'swimming') out.push(['Pace', f.pace_100m_s ? `${duration(f.pace_100m_s)} /100m` : '—'],
    ['SWOLF', num(f.swolf)], ['Lengths', num(f.lengths)], ['Main stroke', f.main_stroke ?? '—'])
  if (s.sport === 'strength') out.push(['Sets', num(f.total_sets)], ['Volume', `${num(f.total_volume)} kg`])
  if (s.rpe != null) out.push(['Your effort', `${num(s.rpe)}/10`])
  if (s.feel != null) out.push(['How you felt', feelLabel(s.feel)])
  return out
}

function StreamChart({ s }: { s: SessionDetail }) {
  const st = s.streams
  if (!st || !st.t.length) return null
  const running = s.sport === 'running'
  // 30-second rolling mean (6 points at 5 s) so pace/power are readable; HR is smooth already
  const smooth = (xs: (number | null)[] | null, w = 6) => xs?.map((_, i) => {
    const win = xs.slice(Math.max(0, i - w + 1), i + 1).filter((v): v is number => v != null)
    return win.length ? win.reduce((a, b) => a + b, 0) / win.length : null
  }) ?? null
  const spd = smooth(st.speed)
  const pwr = smooth(st.power)
  const data = st.t.map((t, i) => ({
    min: +(t / 60).toFixed(1),
    hr: st.hr?.[i] ?? null,
    pace: running && spd?.[i] && spd[i]! > 1.2 ? 1000 / spd[i]! : null,
    power: pwr?.[i] ?? null,
    speed: !running && spd?.[i] ? spd[i]! * 3.6 : null,
  }))
  const second = running ? 'pace' : st.power ? 'power' : st.speed ? 'speed' : null
  const fmtPace = (v: number) => `${Math.floor(v / 60)}:${String(Math.round(v % 60)).padStart(2, '0')}`
  return (
    <div className="card span-12">
      <div className="card-title">Heart rate{second ? ` & ${second}` : ''}</div>
      <div className="chart-tall">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="min" type="number" domain={['dataMin', 'dataMax']} tickFormatter={v => `${Math.round(v)}′`} />
            <YAxis yAxisId="hr" domain={['dataMin - 5', 'dataMax + 5']} width={44} />
            {second && (
              <YAxis yAxisId="b" orientation="right" width={56} reversed={second === 'pace'}
                     domain={['auto', 'auto']} tickFormatter={second === 'pace' ? fmtPace : (v: number) => String(Math.round(v))} />
            )}
            <Tooltip formatter={(v, k) => k === 'pace' ? [`${fmtPace(Number(v))} /km`, 'Pace'] : [Math.round(Number(v)), String(k)]}
                     labelFormatter={v => `${v} min`} />
            <Line yAxisId="hr" dataKey="hr" stroke="var(--worse)" dot={false} strokeWidth={1.8} isAnimationActive={false} name="HR" />
            {second && <Line yAxisId="b" dataKey={second} stroke="var(--primary)" dot={false} strokeWidth={1.8} isAnimationActive={false} connectNulls />}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="muted" style={{ fontSize: 14 }}>Red = heart rate (left axis){second ? ` · blue = ${second} (right axis)` : ''}</div>
    </div>
  )
}

export function SessionDetailView() {
  const { id } = useParams()
  const nav = useNavigate()
  const { data: s, error } = useFetch(() => api.session(id!), [id])
  if (error) return <div className="card">Could not load session: {error}</div>
  if (!s) return <div className="muted">Loading…</div>
  const v = s.verdict
  const f = s.features || {}
  const laps = s.streams?.laps ?? []
  const t = v?.trend

  const setsByEx: Record<string, typeof s.sets> = {}
  s.sets.forEach(x => { (setsByEx[x.exercise] ??= []).push(x) })
  const exLabel = (k: string) => f.exercises?.[k]?.label ?? k

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="row muted"><SportIcon sport={s.sport} size={20} /> {SPORT_LABEL[s.sport]} · {TYPE_LABEL[s.session_type] ?? s.session_type} · {when(s.start_time)}</div>
          <h1>{s.name || SPORT_LABEL[s.sport]}</h1>
          {v && <div className="row"><VerdictPill verdict={v.verdict} /> <span style={{ fontSize: 20 }}>{v.headline}</span> <span className="pill">Confidence: {v.confidence}</span></div>}
        </div>
      </div>

      <div className="detail-grid">
        {v && (
          <div className="card span-7">
            <div className="card-title">Why</div>
            <ul style={{ margin: 0, paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {v.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
            {v.context.some(c => c.kind !== 'rpe') && (
              <div className="row" style={{ marginTop: 14 }}>
                {v.context.filter(c => c.kind !== 'rpe').map((c, i) => <span key={i} className="pill tone-warn"><AlertTriangle size={14} /> {c.text}</span>)}
              </div>
            )}
          </div>
        )}
        {t && (
          <div className="span-5">
            <Improvements items={s.improvements ?? []} formTomorrow={t.form_tomorrow}
                          onClick={() => nav(`/u/${s.user_id}/load`)} />
          </div>
        )}

        {v && v.deltas.length > 0 && (
          <div className="card span-12">
            <div className="card-title">Compared with your similar sessions</div>
            <DeltaTable deltas={v.deltas} />
          </div>
        )}

        <div className="card span-12">
          <div className="card-title">Every number</div>
          <div className="kv">
            {facts(s).map(([k, val]) => <div key={k}><div className="k">{k}</div><div className="v num">{val}</div></div>)}
          </div>
          {Array.isArray(f.zones) && (
            <div style={{ marginTop: 16 }}>
              <div className="k muted" style={{ fontSize: 13, textTransform: 'uppercase' }}>Time in HR zones</div>
              <div className="sleep-bar" style={{ height: 18 }}>
                {f.zones.map((z: number, i: number) => (
                  <span key={i} title={`Z${i + 1}`} style={{ width: `${z * 100}%`, background: ['#64748b', '#38bdf8', '#22c55e', '#f59e0b', '#ef4444'][i] }} />
                ))}
              </div>
              <div className="row muted" style={{ fontSize: 14, marginTop: 4 }}>
                {f.zones.map((z: number, i: number) => <span key={i}>Z{i + 1} {Math.round(z * 100)}%</span>)}
              </div>
            </div>
          )}
        </div>

        <StreamChart s={s} />

        {s.sport === 'cycling' && f.power_curve && (
          <div className="card span-6">
            <div className="card-title">Power curve (best efforts)</div>
            <div className="chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={Object.entries(f.power_curve).map(([d, w]) => ({ d: ({ '5': '5 s', '60': '1 min', '300': '5 min', '1200': '20 min' } as Record<string, string>)[d] ?? d, w }))}>
                  <XAxis dataKey="d" /><YAxis width={44} />
                  <Tooltip formatter={v => [`${Math.round(Number(v))} W`, 'Best']} />
                  <Bar dataKey="w" fill="var(--primary)" radius={[6, 6, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {laps.length > 0 && s.sport !== 'strength' && (
          <div className="card span-6">
            <div className="card-title">Laps</div>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>#</th><th className="num">Time</th><th className="num">Dist</th><th className="num">{s.sport === 'running' ? 'Pace' : s.sport === 'cycling' && s.has_power ? 'Power' : 'Speed'}</th><th className="num">HR</th></tr></thead>
                <tbody>
                  {laps.map((l, i) => (
                    <tr key={i}>
                      <td>{i + 1}</td><td className="num">{duration(l.duration_s)}</td><td className="num">{distance(l.distance_m, s.sport)}</td>
                      <td className="num">{s.sport === 'running' ? pace(l.avg_speed) : l.avg_power ? `${num(l.avg_power)} W` : `${kmh(l.avg_speed)}`}</td>
                      <td className="num">{num(l.avg_hr)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {s.sets.length > 0 && (
          <div className="card span-6">
            <div className="card-title">Sets</div>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Exercise</th><th className="num">Sets</th><th>Reps × kg</th><th className="num">e1RM</th></tr></thead>
                <tbody>
                  {Object.entries(setsByEx).map(([ex, sets]) => (
                    <tr key={ex}>
                      <td>{exLabel(ex)}</td><td className="num">{sets.length}</td>
                      <td className="num">{sets.map(x => `${x.reps ?? '?'}×${x.weight_kg ?? '?'}`).join('  ')}</td>
                      <td className="num">{num(f.exercises?.[ex]?.e1rm, 1)} kg</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {s.baseline_sessions.length > 0 && (
          <div className="card span-6">
            <div className="card-title">Baseline: the sessions you were compared with</div>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>When</th><th className="num">Duration</th><th className="num">Dist</th><th className="num">Avg HR</th><th className="num">Key metric</th></tr></thead>
                <tbody>
                  {s.baseline_sessions.map(b => (
                    <tr key={b.id} className="clickable" onClick={() => nav(`/session/${encodeURIComponent(b.id)}`)}>
                      <td>{when(b.start_time)}</td><td className="num">{duration(b.duration_s)}</td>
                      <td className="num">{distance(b.distance_m, s.sport)}</td><td className="num">{num(b.avg_hr)}</td>
                      <td className="num">{v?.deltas[0] ? keyMetric(s.sport, b.features) : '—'}</td>
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

function keyMetric(sport: string, f: Record<string, any>): string {
  if (sport === 'running') return num(f?.ef_adj, 2)
  if (sport === 'cycling') return f?.ef ? `${num(f.ef, 2)} W/b` : '—'
  if (sport === 'swimming') return f?.pace_100m_s ? `${duration(f.pace_100m_s)}/100` : '—'
  if (sport === 'strength') return `${num(f?.total_volume)} kg`
  return '—'
}
