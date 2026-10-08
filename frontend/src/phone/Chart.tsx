import type { KeyboardEvent, PointerEvent } from 'react'

/** A labelled gridline. `ref` draws it dashed in the chart's ref colour (8 h of sleep, form 0, sweet spot edges). */
export interface Tick { value: number; label: string; ref?: boolean }

export interface Line { values: (number | null)[]; color: string; width?: number; dash?: boolean; area?: boolean }

/** Gridlines at a round step (1, 2, 5 × 10ⁿ, or 25 from tens up, never under `minStep`) that cover `values`: two to five of them. */
export function niceTicks(values: (number | null)[], fmt: (v: number) => string, unit = '', minStep = 1): { lo: number; hi: number; ticks: Tick[] } {
  const xs = values.filter((v): v is number => v != null && Number.isFinite(v))
  if (!xs.length) return { lo: 0, hi: 1, ticks: [] }
  const min = Math.min(...xs), max = Math.max(...xs)
  const raw = Math.max(minStep, (max - min) / 3)
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = (mag >= 10 ? [1, 2, 2.5, 5, 10] : [1, 2, 5, 10]).map(m => m * mag).find(s => s >= raw)!
  const lo = Math.floor(min / step) * step
  const hi = Math.max(lo + step, Math.ceil(max / step) * step)
  const ticks: Tick[] = []
  for (let k = 0; lo + k * step <= hi + step / 1e6; k++) {
    const t = +(lo + k * step).toFixed(6)
    ticks.push({ value: t, label: fmt(t) })
  }
  if (unit) ticks[ticks.length - 1].label += ` ${unit}`
  return { lo, hi, ticks }
}

/** The last `n` local calendar days, oldest first, as YYYY-MM-DD. */
export function lastDays(n: number, end = new Date()): string[] {
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(end); d.setDate(end.getDate() - (n - 1 - i))
    return isoDay(d)
  })
}

export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** "8 Sep"; with `weekday` "Tue 8 Sep". */
export function dayLabel(iso: string, weekday = false): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString([], weekday
    ? { weekday: 'short', day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short' })
}

/** Start, (middle for 90 days and more,) end of a run of days: "8 Sep · Last night", "Oct ’25 · Apr · Today". */
export function dateAxis(days: string[], end: string): string[] {
  const n = days.length
  const d = (i: number) => new Date(`${days[i]}T12:00:00`)
  const month = (i: number) => d(i).toLocaleDateString([], { month: 'short' })
  if (n >= 300) return [`${month(0)} ’${String(d(0).getFullYear()).slice(2)}`, month(Math.floor((n - 1) / 2)), end]
  if (n <= 7) return [`${d(0).toLocaleDateString([], { weekday: 'short' })} ${d(0).getDate()}`, end]
  const first = dayLabel(days[0])
  return n >= 60 ? [first, dayLabel(days[Math.floor((n - 1) / 2)]), end] : [first, end]
}

const pct = (v: number) => `${v.toFixed(2)}%`

/**
 * A phone chart with its axes: gridline values on the right, dates (or per-bar labels) underneath, optional
 * shaded band, and tap/drag to pick a day or week. Lines skip missing days; bars keep one slot per day, so a
 * missing night is a gap, not a shift. Colours and copy stay with the caller.
 */
export function AxisChart({ n, lo, hi, ticks, lines = [], bars, barColor, band, refColor = 'var(--muted)',
  bandColor = 'rgba(61, 220, 132, 0.14)', axis, barLabels, height = 96, label, picked, onPick }: {
  n: number; lo: number; hi: number; ticks: Tick[]
  lines?: Line[]
  bars?: (number | null)[]; barColor?: (i: number, picked: number | null) => string
  band?: [number, number] | null; bandColor?: string; refColor?: string
  axis?: string[]; barLabels?: string[]
  height?: number; label: string
  picked: number | null; onPick: (i: number | null) => void
}) {
  const span = hi - lo || 1
  const y = (v: number) => (1 - (v - lo) / span) * 100
  const x = (i: number) => (n === 1 ? 0 : (i / (n - 1)) * 300)
  const slotX = (i: number) => bars ? ((i + 0.5) / n) * 100 : (n === 1 ? 0 : (i / (n - 1)) * 100)

  const pickAt = (e: PointerEvent<HTMLButtonElement>) => {
    const box = e.currentTarget.getBoundingClientRect()
    const f = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width))
    onPick(bars ? Math.min(n - 1, Math.floor(f * n)) : Math.round(f * (n - 1)))
  }
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Escape') return onPick(null)
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const i = picked ?? n - 1
    onPick(Math.min(n - 1, Math.max(0, i + (e.key === 'ArrowLeft' ? -1 : 1))))
  }

  const path = (vs: (number | null)[]) => {
    let d = '', pen = false
    vs.forEach((v, i) => {
      if (v == null) { pen = false; return }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)} `
      pen = true
    })
    return d.trim()
  }
  const base = y(Math.min(Math.max(0, lo), hi))

  return (
    <div className="ph-axchart">
      <div className="ph-plot" style={{ height }}>
        {band && <span className="ph-band" style={{ top: pct(y(band[1])), height: pct(y(band[0]) - y(band[1])), background: bandColor }} />}
        {ticks.map(t => (
          <span key={t.value} className={`ph-grid${t.ref ? ' ref' : ''}`}
                style={{ top: pct(y(t.value)), ...(t.ref ? { borderTopColor: refColor } : {}) }} />
        ))}
        {lines.length > 0 && (
          <svg viewBox="0 0 300 100" preserveAspectRatio="none" aria-hidden>
            {lines.filter(l => l.area).map((l, k) => {
              const d = path(l.values)
              return d && <path key={`a${k}`} d={`${d} L300 ${base.toFixed(1)} L0 ${base.toFixed(1)} Z`} fill={l.color} opacity={0.12} />
            })}
            {lines.map((l, k) => (
              <path key={k} d={path(l.values)} fill="none" stroke={l.color} strokeWidth={l.width ?? 2.2}
                    strokeDasharray={l.dash ? '5 4' : undefined} strokeLinejoin="round" strokeLinecap="round"
                    vectorEffect="non-scaling-stroke" />
            ))}
          </svg>
        )}
        {bars && (
          <div className="ph-plot-bars" aria-hidden>
            {bars.map((v, i) => (
              <span key={i}>
                {v == null ? <i className="none" /> : <i style={{ height: pct(Math.max(1, (v - lo) / span * 100)), background: barColor?.(i, picked) }} />}
              </span>
            ))}
          </div>
        )}
        {picked != null && !bars && (
          <>
            <span className="ph-mark" style={{ left: pct(slotX(picked)) }} />
            {lines.map((l, k) => l.values[picked] != null && (
              <span key={k} className="ph-dot" style={{ left: pct(slotX(picked)), top: pct(y(l.values[picked]!)), background: l.color }} />
            ))}
          </>
        )}
        <button type="button" className="ph-scrub" aria-label={`${label}. Tap or drag to read a day; arrow keys step, Escape goes back to the latest.`}
                onPointerDown={e => { e.currentTarget.setPointerCapture?.(e.pointerId); pickAt(e) }}
                onPointerMove={e => { if (e.buttons || e.pointerType !== 'mouse') pickAt(e) }}
                onKeyDown={onKey} />
      </div>
      <div className="ph-yaxis" aria-hidden>
        {ticks.map(t => (
          <span key={t.value} className="num" style={{ top: pct(y(t.value)), ...(t.ref ? { color: refColor } : {}) }}>{t.label}</span>
        ))}
      </div>
      {barLabels ? (
        <div className="ph-xaxis slots" aria-hidden>
          {barLabels.map((t, i) => <span key={i} className={i === picked ? 'on' : ''}>{t}</span>)}
        </div>
      ) : axis && (
        <div className="ph-axis ph-xaxis">{axis.map((t, i) => <span key={i}>{t}</span>)}</div>
      )}
    </div>
  )
}
