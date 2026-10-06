import { AlertTriangle } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Bar, BarChart } from 'recharts'
import { api } from '../api'
import type { Delta, SessionDetail } from '../api'
import { SportIcon, VerdictIcon } from '../components/icons'
import { Improvements } from '../components/Improvements'
import { distance, duration, feelLabel, kmh, num, pace, SPORT_LABEL, TYPE_LABEL, VERDICT_LABEL, when } from '../format'
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

type Row = [string, string]
interface FactGroups { key: Row[]; groups: { title: string; rows: Row[] }[] }

/** The session's numbers: up to 6 key numbers big, the rest in small themed groups. */
function factGroups(s: SessionDetail): FactGroups {
  const f = s.features || {}
  const spm = f.avg_cadence ? `${num(f.avg_cadence * (f.avg_cadence < 120 ? 2 : 1))} spm` : null
  const key: Row[] = [['Duration', duration(s.duration_s)]]
  if (s.distance_m) key.push(['Distance', distance(s.distance_m, s.sport)])
  if (s.sport === 'running' && f.avg_speed) key.push(['Avg pace', `${pace(f.avg_speed)} /km`])
  if (s.sport === 'cycling') key.push(f.avg_power ? ['Avg power', `${num(f.avg_power)} W`] : ['Avg speed', `${kmh(f.avg_speed)} km/h`])
  if (s.sport === 'swimming' && f.pace_100m_s) key.push(['Pace', `${duration(f.pace_100m_s)} /100 m`])
  if (s.sport === 'strength') key.push(['Volume', `${num(f.total_volume)} kg`])
  if (s.avg_hr) key.push(['Avg HR', `${num(s.avg_hr)} bpm`])
  if (s.sport === 'running' && spm) key.push(['Cadence', spm])
  key.push(['Load', num(s.load)])

  const groups: { title: string; rows: Row[] }[] = []
  const add = (title: string, rows: (Row | null | false | undefined)[]) => {
    const r = rows.filter((x): x is Row => !!x && x[1] !== '—')
    if (r.length) groups.push({ title, rows: r })
  }
  if (s.sport === 'running') {
    add('Performance', [
      [`Pace @ ${f.ref_hr ?? ''} bpm`, f.speed_at_ref_hr ? `${pace(f.speed_at_ref_hr)} /km` : '—'],
      ['Grade-adj. pace', f.gap_speed ? `${pace(f.gap_speed)} /km` : '—'],
      ['Efficiency', num(f.ef_adj, 2)],
      ['HR drift', f.decoupling != null ? `${num(f.decoupling, 1)} %` : '—'],
    ])
    if (f.work_speed) {
      add('Intervals', [
        ['Reps', f.rep_s ? `${f.rep_count} × ${duration(f.rep_s)}` : num(f.rep_count)],
        ['Rep pace', `${pace(f.work_speed)} /km`],
        ['Rep HR', `${num(f.work_hr)} bpm`],
        // short reps: HR can't keep up, so the HR drop says little — show how well the pace held instead
        f.rep_s && f.rep_s < 120 ? ['Pace held', f.rep_fade != null ? (f.rep_fade > 0 ? `−${num(f.rep_fade, 1)} %` : 'held') : '—']
          : ['HR drop between reps', `${num(f.hr_recovery)} bpm`],
      ])
    }
  }
  if (s.sport === 'cycling' && f.avg_power) {
    add('Power', [['Norm. power', `${num(f.np)} W`], ['W / beat', num(f.ef, 2)],
      ['Intensity factor', num(f.intensity_factor, 2)], ['eFTP', f.eftp ? `${num(f.eftp)} W` : '—']])
  }
  if (s.sport === 'swimming') add('Swim', [['SWOLF', num(f.swolf)], ['Lengths', num(f.lengths)], ['Main stroke', f.main_stroke ?? '—']])
  if (s.sport === 'strength') add('Lifting', [['Sets', num(f.total_sets)]])
  add('Heart & effort', [
    ['Max HR', s.max_hr ? `${num(s.max_hr)} bpm` : '—'],
    s.ascent_m ? ['Ascent', `${num(s.ascent_m)} m`] : null,
    s.rpe != null ? ['Your effort', `${num(s.rpe)}/10`] : null,
    s.feel != null ? ['How you felt', feelLabel(s.feel)] : null,
  ])
  // Garmin's weather for this activity (station near the start) — not the wrist sensor
  const w = f.weather
  add('Conditions', [
    w ? ['Weather', `${num(w.temp_c)} °C${w.desc ? ` · ${w.desc}` : ''}`] : null,
    w && w.feels_like_c != null && Math.round(w.feels_like_c) !== Math.round(w.temp_c) ? ['Feels like', `${num(w.feels_like_c)} °C`] : null,
    w && w.humidity != null ? ['Humidity', `${num(w.humidity)} %`] : null,
    w && w.wind_kmh != null ? ['Wind', `${num(w.wind_kmh)} km/h${w.wind_dir ? ` ${w.wind_dir}` : ''}`] : null,
    f.heat_adj_pct ? ['Heat adjustment', `+${num(f.heat_adj_pct, 1)} %`] : null,
  ])
  return { key: key.slice(0, 6), groups }
}

const ZONE_COLORS = ['#64748b', '#38bdf8', '#3ddc84', '#f5b83d', '#f87171']

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
            <Line yAxisId="hr" dataKey="hr" stroke="#f87171" dot={false} strokeWidth={1.8} isAnimationActive={false} name="HR" />
            {second && <Line yAxisId="b" dataKey={second} stroke="var(--primary)" dot={false} strokeWidth={1.8} isAnimationActive={false} connectNulls />}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="muted" style={{ fontSize: 14 }}>Red = heart rate (left axis){second ? ` · yellow-green = ${second} (right axis${second === 'pace' ? ', higher = faster' : ''})` : ''}</div>
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
  const numbers = factGroups(s)
  const t = v?.trend

  const setsByEx: Record<string, typeof s.sets> = {}
  s.sets.forEach(x => { (setsByEx[x.exercise] ??= []).push(x) })
  const exLabel = (k: string) => f.exercises?.[k]?.label ?? k

  return (
    <div className="detail">
      <div className="detail-grid">
        <section className={`card hero stripes ${t ? 'span-7' : 'span-12'}`}>
          <div className="stack" style={{ gap: 8 }}>
            <div className="row">
              <span className="pill"><SportIcon sport={s.sport} size={16} /> {SPORT_LABEL[s.sport]} · {TYPE_LABEL[s.session_type] ?? s.session_type}</span>
              <span className="muted">{when(s.start_time)}</span>
            </div>
            <h1 style={{ margin: 0, fontSize: 32, fontWeight: 600 }}>{s.name || SPORT_LABEL[s.sport]}</h1>
            {v && (
              <>
                <div className={`row display tone-${v.verdict}`} style={{ fontSize: 'clamp(64px, calc(var(--vw) * 8), 104px)', gap: 12, color: v.verdict === 'better' ? 'var(--volt)' : undefined }}>
                  <VerdictIcon verdict={v.verdict} size={60} strokeWidth={3} /> {VERDICT_LABEL[v.verdict]}
                </div>
                <div className="display" style={{ fontSize: 28, fontWeight: 800, lineHeight: 1.1 }}>{v.headline}</div>
                <div className="row" style={{ gap: 8 }}>
                  <span className="pill">Confidence: {v.confidence}</span>
                  {s.rpe != null && <span className="pill">Effort {num(s.rpe)}/10{s.feel != null ? ` · ${feelLabel(s.feel)}` : ''}</span>}
                </div>
              </>
            )}
          </div>
        </section>
        {t && (
          <div className="span-5">
            <Improvements items={s.improvements ?? []}
                          onClick={() => nav(`/u/${s.user_id}/load`)} />
          </div>
        )}

        {v && (
          <div className="card span-12">
            <div className="card-title">Why</div>
            <ul className="reasons-list two">
              {v.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
            {v.context.some(c => c.kind !== 'rpe') && (
              <div className="row" style={{ marginTop: 14 }}>
                {v.context.filter(c => c.kind !== 'rpe').map((c, i) => <span key={i} className="pill tone-warn"><AlertTriangle size={14} /> {c.text}</span>)}
              </div>
            )}
          </div>
        )}

        {v && v.deltas.length > 0 && (
          <div className="card span-12">
            <div className="card-title">Compared with your {v.deltas[0]?.n ?? ''} similar sessions</div>
            <DeltaTable deltas={v.deltas} />
          </div>
        )}

        <div className="card span-12">
          <div className="card-title">The numbers</div>
          <div className="key-facts">
            {numbers.key.map(([k, val]) => <div key={k} className="tile"><div className="label">{k}</div><div className="v">{val}</div></div>)}
          </div>
          <div className="fact-groups">
            {numbers.groups.map(g => (
              <div key={g.title} className="fact-group">
                <div className="label">{g.title}</div>
                <dl>{g.rows.map(([k, val]) => <div key={k}><dt>{k}</dt><dd className="num">{val}</dd></div>)}</dl>
              </div>
            ))}
            {Array.isArray(f.zones) && (
              <div className="fact-group">
                <div className="label">Time in HR zones</div>
                <div className="zone-bars">
                  {f.zones.map((z: number, i: number) => (
                    <div key={i}><span className="num">Z{i + 1}</span><i><b style={{ width: `${z * 100}%`, background: ZONE_COLORS[i] }} /></i><span className="num">{Math.round(z * 100)}%</span></div>
                  ))}
                </div>
              </div>
            )}
          </div>
          {f.weather?.station && <div className="faint small" style={{ marginTop: 10 }}>Weather from Garmin · station {f.weather.station}</div>}
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
