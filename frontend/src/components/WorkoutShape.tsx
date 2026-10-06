import type { WorkoutStep } from '../api'
import { stepLook, stepSeconds } from '../mission'

/** The workout's shape: one bar per step, width = time, height = intensity. */
export function WorkoutShape({ steps, height = 34, labels, easy = false }: {
  steps: WorkoutStep[]; height?: number; labels?: (step: WorkoutStep) => string | null; easy?: boolean
}) {
  if (!steps.length) return null
  return (
    <div className="wshape" style={{ height }} aria-hidden>
      {steps.map((s, i) => {
        const look = stepLook(s, easy)
        const label = labels?.(s)
        return (
          <div key={i} className="wshape-col" style={{ flexGrow: stepSeconds(s) }}>
            {label && <span className="wshape-label num" style={{ color: look.color === 'var(--volt)' ? 'var(--volt)' : 'var(--muted)' }}>{label}</span>}
            <i style={{ height: `${look.h * 100}%`, background: look.color }} />
          </div>
        )
      })}
    </div>
  )
}
