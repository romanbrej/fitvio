import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../../api'
import type { HealthDay } from '../../api'
import { hoursMinutes, num } from '../../format'
import { AxisChart, dateAxis, dayLabel, lastDays, niceTicks } from '../Chart'
import type { Line, Tick } from '../Chart'
import { usePhone } from '../ctx'
import { Card } from '../parts'
import { bodyBatteryNote, hrvBand } from '../util'
import type { Note } from '../util'
import { TrendsNav } from './Trends'

const RANGES = [7, 30, 90, 365] as const
const SLEEP_GOAL_MIN = 480

/** One value per calendar day of the range (null where there's no row), so the x axis is real dates. */
function column(days: string[], rows: Map<string, HealthDay>, k: keyof HealthDay): (number | null)[] {
  return days.map(d => { const v = rows.get(d)?.[k]; return typeof v === 'number' ? v : null })
}

/** "▼ 3 bpm in 30 days", coloured by whether that direction is good. */
function change(values: (number | null)[], unit: string, dp: number, goodUp: boolean): Note | null {
  const xs = values.filter((v): v is number => v != null)
  if (xs.length < 2) return null
  const diff = xs[xs.length - 1] - xs[0]
  if (Math.abs(diff) < (dp ? 0.1 : 1)) return { text: `→ steady over ${values.length} days`, tone: 'muted' }
  return { text: `${diff > 0 ? '▲' : '▼'} ${Math.abs(diff).toFixed(dp)}${unit} in ${values.length} days`, tone: diff > 0 === goodUp ? 'better' : 'worse' }
}

interface Metric {
  id: string; label: string; unit?: string; latest: string; fmt: (v: number) => string
  end: string; note?: Note | null
  values: (number | null)[]; color: string; asBars?: boolean
  lo: number; hi: number; ticks: Tick[]; band?: [number, number] | null; refColor?: string; height?: number
}

function MetricCard({ m, days, focus, picked, onPick }: {
  m: Metric; days: string[]; focus: string | null; picked: number | null; onPick: (i: number | null) => void
}) {
  const v = picked == null ? null : m.values[picked]
  const value = picked == null ? m.latest : v == null ? '—' : m.fmt(v)
  const when = picked == null || picked === days.length - 1 ? m.end : dayLabel(days[picked], true)
  const lines: Line[] = m.asBars ? [] : [{ values: m.values, color: m.color }]
  return (
    <Card id={`m-${m.id}`} className={focus === m.id ? 'ph-focus' : ''}>
      <div className="ph-row" style={{ alignItems: 'flex-start' }}>
        <div><span className="ph-label">{m.label}</span><span className={`ph-when${picked != null ? ' on' : ''}`}>{picked != null && v == null ? `${when} · no data` : when}</span></div>
        <span className="ph-right"><b className="num ph-v">{value}</b>{m.unit && (picked == null || v != null) && <span className="ph-unit"> {m.unit}</span>}</span>
      </div>
      {m.note && <span className={`ph-foot tone-${m.note.tone}`}>{m.note.text}</span>}
      <AxisChart n={days.length} lo={m.lo} hi={m.hi} ticks={m.ticks} band={m.band} refColor={m.refColor}
                 lines={lines} bars={m.asBars ? m.values : undefined}
                 barColor={(i, p) => p == null ? m.color : i === p ? '#e0e7ff' : '#5b5fc7'}
                 axis={dateAxis(days, m.end)} height={m.height ?? 96}
                 label={`${m.label}, last ${days.length} days`} picked={picked} onPick={onPick} />
    </Card>
  )
}

function sleepScale(values: (number | null)[], bars: boolean) {
  const max = Math.max(600, ...values.map(v => v ?? 0))
  const hi = Math.ceil(max / 120) * 120
  const lo = bars ? 0 : Math.min(240, Math.floor(Math.min(...values.map(v => v ?? 240)) / 120) * 120)
  const ticks: Tick[] = bars ? [{ value: 0, label: '0' }, { value: 240, label: '4 h' }]
    : Array.from({ length: (SLEEP_GOAL_MIN - lo) / 120 }, (_, k) => ({ value: lo + k * 120, label: `${(lo + k * 120) / 60} h` }))
  ticks.push({ value: SLEEP_GOAL_MIN, label: '8 h', ref: true })
  return { lo, hi, ticks }
}

export function Health() {
  const { me, ambient } = usePhone()
  const a = ambient!
  const [params] = useSearchParams()
  const focus = params.get('metric')
  const [range, setRange] = useState<number>(30)
  const [rows, setRows] = useState<HealthDay[] | null>(null)
  const [picks, setPicks] = useState<Record<string, number | null>>({})
  useEffect(() => {
    let alive = true
    api.health(me.id, range).then(d => alive && setRows(d)).catch(() => alive && setRows([]))
    return () => { alive = false }
  }, [me.id, range])
  useEffect(() => {
    // arriving from a tile on Today: show that metric first
    if (focus && rows) document.getElementById(`m-${focus}`)?.scrollIntoView({ block: 'center' })
  }, [focus, rows])

  const h = a.health_latest
  const band = hrvBand(h)
  const hrvBelow = h.hrv_last_night != null && band != null && h.hrv_last_night < band[0]
  const hrvNote: Note | null = h.hrv_last_night == null || !band ? null : {
    text: `${hrvBelow ? '▼ below' : h.hrv_last_night > band[1] ? '▲ above' : 'in'} your normal range (${band[0]}–${band[1]} ms)`,
    tone: hrvBelow ? 'worse' : 'better',
  }
  const bb = bodyBatteryNote(h.bb_max)

  const metrics = (): Metric[] => {
    const days = lastDays(range)
    const byDay = new Map(rows!.map(r => [r.day, r]))
    const col = (k: keyof HealthDay) => column(days, byDay, k)
    const int = (v: number) => String(Math.round(v))

    const hrv = col('hrv_last_night')
    const rhr = col('rhr')
    const sleep = col('sleep_total_min')
    const sleepBars = range <= 30
    const out: Metric[] = [
      { id: 'hrv', label: 'HRV · overnight', unit: 'ms', latest: num(h.hrv_last_night), fmt: int, end: 'Last night', note: hrvNote,
        values: hrv, color: 'var(--better)', band, height: 120,
        ...niceTicks([...hrv, ...(band ?? [])], int, 'ms') },
      { id: 'rhr', label: 'Resting HR', unit: 'bpm', latest: num(h.rhr), fmt: int, end: 'Today', note: change(rhr, ' bpm', 0, false),
        values: rhr, color: 'var(--worse)', ...niceTicks(rhr, int, 'bpm') },
      { id: 'sleep', label: 'Sleep', latest: hoursMinutes(h.sleep_total_min), fmt: hoursMinutes, end: 'Last night',
        note: h.sleep_score != null ? { text: `Score ${num(h.sleep_score)}`, tone: 'muted' } : null,
        values: sleep, color: '#818cf8', refColor: '#a5b4fc', asBars: sleepBars, ...sleepScale(sleep, sleepBars) },
    ]
    if (a.source === 'intervals') {
      const steps = col('steps')
      const k = (v: number) => v >= 1000 ? `${+(v / 1000).toFixed(1)}k` : int(v)
      out.push({ id: 'steps', label: 'Steps', latest: num(h.steps), fmt: v => Math.round(v).toLocaleString(), end: 'Today',
        values: steps, color: 'var(--fitness)', ...niceTicks(steps, k) })
    } else {
      out.push({ id: 'body_battery', label: 'Body Battery', latest: num(h.bb_max), fmt: int, end: 'Today',
        note: bb, values: col('bb_max'), color: 'var(--volt)',
        lo: 0, hi: 100, ticks: [0, 50, 100].map(t => ({ value: t, label: String(t) })) })
    }
    // VO₂max changes every few days: carry each value forward until the next one
    const vo2s = [...a.vo2max].sort((p, q) => p.day.localeCompare(q.day))
    let at = -1
    const vo2 = days.map(d => { while (at + 1 < vo2s.length && vo2s[at + 1].day <= d) at++; return at >= 0 ? vo2s[at].value : null })
    if (vo2s.some(v => v.day >= days[0]) && vo2.filter(v => v != null).length > 1) {
      out.push({ id: 'vo2max', label: 'VO₂max', unit: 'ml/kg/min', latest: vo2s.at(-1)!.value.toFixed(1), fmt: v => v.toFixed(1), end: 'Today',
        note: change(vo2, '', 1, true), values: vo2, color: 'var(--fitness)', ...niceTicks(vo2, v => v.toFixed(1), '', 0.5) })
    }
    return out
  }

  const pickRange = (r: number) => { setRange(r); setPicks({}) }

  return (
    <div className="ph-stack">
      <h1 className="ph-title">Trends</h1>
      <TrendsNav on="health" />
      <div className="ph-row" role="group" aria-label="Range" style={{ gap: 8 }}>
        {RANGES.map(r => (
          <button key={r} className="ph-chip-btn" aria-pressed={range === r} onClick={() => pickRange(r)}>{r} d</button>
        ))}
      </div>

      {!rows ? <div className="ph-boot">Loading…</div> : metrics().map(m => (
        <MetricCard key={m.id} m={m} days={lastDays(range)} focus={focus} picked={picks[m.id] ?? null}
                    onPick={i => setPicks(p => ({ ...p, [m.id]: i }))} />
      ))}
    </div>
  )
}
