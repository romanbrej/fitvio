/** Minimal SVG sparkline with a highlighted last point. Plain SVG keeps the wall view light. */
export function Sparkline({ values, color = 'var(--primary)', height = 44, band }: {
  values: number[]; color?: string; height?: number; band?: [number, number] | null
}) {
  if (values.length < 2) return <div style={{ height }} className="faint" aria-hidden />
  const w = 200
  const pad = 4
  const lo = Math.min(...values, ...(band ? [band[0]] : []))
  const hi = Math.max(...values, ...(band ? [band[1]] : []))
  const span = hi - lo || 1
  const x = (i: number) => pad + (i / (values.length - 1)) * (w - 2 * pad)
  const y = (v: number) => pad + (1 - (v - lo) / span) * (height - 2 * pad)
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const last = values[values.length - 1]
  return (
    <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} preserveAspectRatio="none" aria-hidden>
      {band && (
        <rect x={0} width={w} y={y(band[1])} height={Math.max(1, y(band[0]) - y(band[1]))}
              fill="var(--better)" opacity={0.12} />
      )}
      <path d={d} fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round"
            vectorEffect="non-scaling-stroke" />
      <circle cx={x(values.length - 1)} cy={y(last)} r={4} fill={color} />
    </svg>
  )
}
