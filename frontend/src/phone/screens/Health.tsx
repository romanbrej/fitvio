import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../../api'
import type { HealthDay } from '../../api'
import { Sparkline } from '../../components/Sparkline'
import { hoursMinutes, num } from '../../format'
import { usePhone } from '../ctx'
import { Card } from '../parts'
import { bodyBatteryNote, hrvBand } from '../util'
import { TrendsNav } from './Trends'

const RANGES = [7, 30, 90, 365] as const

function series(days: HealthDay[], k: keyof HealthDay): number[] {
  return days.map(d => d[k]).filter((v): v is number => typeof v === 'number')
}

function Metric({ id, focus, label, value, unit, note, tone, children }: {
  id: string; focus: string | null; label: string; value: string; unit?: string; note?: string | null; tone?: string; children: React.ReactNode
}) {
  return (
    <Card id={`m-${id}`} className={focus === id ? 'ph-focus' : ''}>
      <div className="ph-row">
        <span className="ph-label">{label}</span>
        <span className="ph-right"><b className="num ph-v">{value}</b>{unit && <span className="ph-unit"> {unit}</span>}</span>
      </div>
      {note && <span className={`ph-foot tone-${tone ?? 'muted'}`}>{note}</span>}
      {children}
    </Card>
  )
}

export function Health() {
  const { me, ambient } = usePhone()
  const a = ambient!
  const [params] = useSearchParams()
  const focus = params.get('metric')
  const [range, setRange] = useState<number>(30)
  const [days, setDays] = useState<HealthDay[] | null>(null)
  useEffect(() => {
    let alive = true
    api.health(me.id, range).then(d => alive && setDays(d)).catch(() => alive && setDays([]))
    return () => { alive = false }
  }, [me.id, range])
  useEffect(() => {
    // arriving from a tile on Today: show that metric first
    if (focus && days) document.getElementById(`m-${focus}`)?.scrollIntoView({ block: 'center' })
  }, [focus, days])

  const h = a.health_latest
  const band = hrvBand(h)
  const hrvBelow = h.hrv_last_night != null && band != null && h.hrv_last_night < band[0]
  const hrvNote = h.hrv_last_night == null || !band ? null
    : `${hrvBelow ? '▼ below' : h.hrv_last_night > band[1] ? '▲ above' : 'in'} your normal range (${band[0]}–${band[1]} ms)`
  const bb = bodyBatteryNote(h.bb_max)
  const sleep = days ? days.filter(d => d.sleep_total_min != null) : []
  const since = new Date(Date.now() - range * 86400000).toISOString().slice(0, 10)
  const vo2 = a.vo2max.filter(v => v.day >= since)

  return (
    <div className="ph-stack">
      <h1 className="ph-title">Trends</h1>
      <TrendsNav on="health" />
      <div className="ph-row" role="group" aria-label="Range" style={{ gap: 8 }}>
        {RANGES.map(r => (
          <button key={r} className="ph-chip-btn" aria-pressed={range === r} onClick={() => setRange(r)}>{r} d</button>
        ))}
      </div>

      {!days ? <div className="ph-boot">Loading…</div> : (
        <>
          <Metric id="hrv" focus={focus} label="HRV · overnight" value={num(h.hrv_last_night)} unit="ms" note={hrvNote} tone={hrvBelow ? 'worse' : 'better'}>
            <Sparkline values={series(days, 'hrv_last_night')} height={120} color="var(--better)" band={band} />
          </Metric>
          <Metric id="rhr" focus={focus} label="Resting HR" value={num(h.rhr)} unit="bpm">
            <Sparkline values={series(days, 'rhr')} height={90} color="var(--worse)" />
          </Metric>
          <Metric id="sleep" focus={focus} label="Sleep" value={hoursMinutes(h.sleep_total_min)}
                  note={h.sleep_score != null ? `Score ${num(h.sleep_score)}` : null}>
            {range <= 30 ? (
              <div className="ph-bars sleep" aria-label={`Sleep per night, last ${range} days`}>
                {sleep.map(d => <div key={d.day}><i style={{ height: `${Math.min(100, d.sleep_total_min! / 600 * 100)}%` }} /></div>)}
              </div>
            ) : <Sparkline values={series(days, 'sleep_total_min')} height={90} color="#818cf8" />}
          </Metric>
          {a.source === 'intervals' ? (
            <Metric id="steps" focus={focus} label="Steps" value={num(h.steps)}>
              <Sparkline values={series(days, 'steps')} height={90} color="var(--fitness)" />
            </Metric>
          ) : (
            <Metric id="body_battery" focus={focus} label="Body Battery" value={num(h.bb_max)}
                    note={bb?.text} tone={bb?.tone}>
              <Sparkline values={series(days, 'bb_max')} height={90} color="var(--volt)" />
            </Metric>
          )}
          {vo2.length > 1 && (
            <Metric id="vo2max" focus={focus} label="VO₂max" value={vo2.at(-1)!.value.toFixed(1)}>
              <Sparkline values={vo2.map(v => v.value)} height={90} color="var(--fitness)" />
            </Metric>
          )}
        </>
      )}
    </div>
  )
}
