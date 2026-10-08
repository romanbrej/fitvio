import type { SessionDetail } from '../api'
import { duration, num } from '../format'
import './SetList.css'

type Set = SessionDetail['sets'][number]

const kg = (w: number) => String(+w.toFixed(1))

/**
 * Sets like a gym log: each exercise once, then one row per set (weight, reps, or the time of a timed set).
 * Columns only appear when some set has them, so a plank shows Set · Time and a deadlift Set · kg · Reps.
 */
export function SetList({ sets, exercises, wall = false }: {
  sets: Set[]; exercises?: Record<string, { label?: string; e1rm?: number | null }>; wall?: boolean
}) {
  const byEx = new Map<string, Set[]>()
  sets.forEach(x => byEx.set(x.exercise, [...(byEx.get(x.exercise) ?? []), x]))
  return (
    <div className={`setlist${wall ? ' wall' : ''}`}>
      {[...byEx].map(([ex, rows]) => {
        const info = exercises?.[ex]
        const hasKg = rows.some(x => x.weight_kg)
        const hasReps = rows.some(x => x.reps)
        const hasTime = rows.some(x => !x.reps && x.duration_s)
        return (
          <section key={ex} className="setlist-ex">
            <div className="setlist-head">
              <span className="setlist-name">{info?.label ?? ex}</span>
              <span className="setlist-meta num">
                {rows.length} {rows.length === 1 ? 'set' : 'sets'}{info?.e1rm != null && ` · e1RM ${num(info.e1rm, 1)} kg`}
              </span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Set</th>
                  {hasKg && <th className="num">kg</th>}
                  {(hasReps || !hasTime) && <th className="num">Reps</th>}
                  {hasTime && <th className="num">Time</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((x, i) => (
                  <tr key={x.set_index}>
                    <td className="setlist-no">{i + 1}</td>
                    {hasKg && <td className="num">{x.weight_kg ? kg(x.weight_kg) : '—'}</td>}
                    {(hasReps || !hasTime) && <td className="num">{x.reps || '—'}</td>}
                    {hasTime && <td className="num">{!x.reps && x.duration_s ? duration(x.duration_s) : '—'}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
    </div>
  )
}
