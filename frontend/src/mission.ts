/** "Today's mission": the wall's headline and the wording around Garmin's readiness and workouts. */
import type { Ambient, PlannedWorkout, Readiness, WorkoutStep } from './api'

/** 312 → "5:12" (seconds per km). */
export function paceStr(sPerKm: number | null | undefined): string {
  if (!sPerKm) return '—'
  const s = Math.round(sPerKm)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** 2220 → "37 min", 5400 → "1:30 h". */
export function minutes(sec: number | null | undefined): string {
  if (!sec) return '—'
  const m = Math.round(sec / 60)
  return m >= 90 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')} h` : `${m} min`
}

export const READINESS_LEVEL: Record<string, string> = {
  PRIME: 'Prime', HIGH: 'High', MODERATE: 'Moderate', LOW: 'Low', POOR: 'Poor',
}

/** Garmin's short feedback keys → words. Unknown keys are shown as Garmin sends them, made readable. */
const FEEDBACK: Record<string, string> = {
  WELL_RESTED: 'Well rested', WELL_RECOVERED: 'Well recovered', READY_FOR_THE_DAY: 'Ready for the day',
  RECOVERING: 'Still recovering', GOOD_RECOVERY: 'Good recovery', LOW_HRV: 'HRV is low', POOR_SLEEP: 'Poor sleep',
  HIGH_TRAINING_LOAD: 'High training load', REST_RECOMMENDED: 'Rest recommended', LET_YOUR_BODY_RECOVER: 'Let your body recover',
}

export function feedbackText(key: string | null | undefined): string | null {
  if (!key) return null
  return FEEDBACK[key] ?? key.toLowerCase().replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
}

/** Garmin's workout purpose (LACTATE_THRESHOLD …) → a short label. */
const PHRASE: Record<string, string> = {
  RECOVERY: 'Recovery', AEROBIC_BASE: 'Base', BASE: 'Base', LONG_RUN: 'Long run', TEMPO: 'Tempo',
  LACTATE_THRESHOLD: 'Threshold', THRESHOLD: 'Threshold', VO2MAX: 'VO₂max', ANAEROBIC_CAPACITY: 'Anaerobic',
  ANAEROBIC: 'Anaerobic', SPRINT: 'Sprint', SPEED: 'Speed',
}
export function phraseLabel(p: string | null | undefined): string | null {
  if (!p) return null
  return PHRASE[p.toUpperCase()] ?? p.toLowerCase().replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
}

/** Intensity of a step for the workout's shape (0–1) and its colour. */
export function stepLook(step: WorkoutStep): { h: number; color: string } {
  switch (step.kind) {
    case 'warmup': return { h: 0.45, color: 'var(--inline)' }
    case 'cooldown': return { h: 0.32, color: '#475569' }
    case 'recovery': case 'rest': return { h: 0.24, color: '#475569' }
    case 'interval': case 'main': case 'active': return { h: 0.9, color: 'var(--volt)' }
    default: return { h: 0.5, color: 'var(--muted)' }
  }
}

/** A step's length in seconds for drawing (distance steps: at their target pace, else 6 min/km). */
export function stepSeconds(step: WorkoutStep): number {
  if (step.duration_s) return step.duration_s
  if (step.distance_m) {
    const p = step.target?.type === 'pace' ? (step.target.low_s_per_km + step.target.high_s_per_km) / 2 : 360
    return step.distance_m / 1000 * p
  }
  return 60
}

export function targetText(step: WorkoutStep): string | null {
  const t = step.target
  if (!t) return null
  if (t.type === 'pace') return `${paceStr(t.low_s_per_km)}–${paceStr(t.high_s_per_km)} /km`
  if (t.type === 'hr') return `HR ${t.low}–${t.high}`
  if (t.type === 'hr_zone') return `HR zone ${t.zone}`
  if (t.type === 'power') return `${t.low}–${t.high} W`
  if (t.type === 'cadence') return `${t.low}–${t.high} spm`
  return null
}

export function stepLength(step: WorkoutStep): string {
  if (step.duration_s) {
    const m = Math.floor(step.duration_s / 60), s = Math.round(step.duration_s % 60)
    return s ? `${m}:${String(s).padStart(2, '0')}` : `${m}′`
  }
  if (step.distance_m) return step.distance_m >= 1000 ? `${(step.distance_m / 1000).toFixed(1)} km` : `${step.distance_m} m`
  return 'lap'
}

const KIND_LABEL: Record<string, string> = {
  warmup: 'Warm-up', cooldown: 'Cool-down', interval: 'Work', recovery: 'Recovery', rest: 'Rest', other: 'Step',
}
export const stepKindLabel = (k: string) => KIND_LABEL[k] ?? k.replace(/^./, c => c.toUpperCase())

/** "15′ warm-up · 3 × 10′ @ 4:55–5:15 /km · 9′ cool-down" — the one-line summary on the wall. */
export function workoutSummary(w: PlannedWorkout): string[] {
  const steps = w.steps ?? []
  const parts: string[] = []
  const warm = steps.find(s => s.kind === 'warmup')
  const cool = [...steps].reverse().find(s => s.kind === 'cooldown')
  const work = steps.filter(s => !['warmup', 'cooldown', 'recovery', 'rest'].includes(s.kind))
  if (warm) parts.push(`${stepLength(warm)} warm-up`)
  if (work.length) {
    const t = targetText(work[0])
    const same = work.every(s => stepLength(s) === stepLength(work[0]))
    parts.push(`${work.length > 1 && same ? `${work.length} × ` : ''}${stepLength(work[0])}${t ? ` @ ${t}` : ''}`)
  }
  if (cool) parts.push(`${stepLength(cool)} cool-down`)
  return parts
}

/** The big headline, from Garmin's readiness (or form when there's none) and today's plan. */
export function headline(a: Ambient): { title: string; sub: string } {
  const r: Readiness | null = a.readiness
  const w = a.today_workout
  const form = a.form?.form ?? null
  if (w?.done) {
    return {
      title: w.done.verdict === 'better' ? 'Mission complete.' : 'Done for today.',
      sub: 'Recover well — that’s where you get faster.',
    }
  }
  const level = r?.level ?? null
  if (level === 'LOW' || level === 'POOR') {
    return { title: w ? 'Easy does it.' : 'Recover today.', sub: feedbackText(r?.feedback) ?? 'Your body asks for an easy day.' }
  }
  if (level === 'PRIME' || level === 'HIGH' || (!level && form != null && form > 5)) {
    return { title: 'Ready to push.', sub: feedbackText(r?.feedback) ?? 'Form is fresh — a good day to go hard.' }
  }
  if (!level && form != null && form < -30) {
    return { title: 'Recover today.', sub: 'Fatigue is high — an easy day keeps the gains.' }
  }
  return { title: 'Keep building.', sub: feedbackText(r?.feedback) ?? 'Steady work today adds up.' }
}
