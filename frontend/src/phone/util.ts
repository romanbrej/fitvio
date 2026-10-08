import type { Ambient, Session, Sport, VerdictKind } from '../api'
import { pace } from '../format'

/** The four sports with their own card (Today), trend row (Trends) and history page. */
export const MAIN_SPORTS: Sport[] = ['running', 'cycling', 'swimming', 'strength']

/** The verdict's colour: Better gets the volt accent, like on the wall. Always shown with its icon and word. */
export const VERDICT_COLOR: Record<VerdictKind, string> = {
  better: 'var(--volt)', in_line: 'var(--inline)', worse: 'var(--worse)', not_comparable: 'var(--na)', load_only: 'var(--load)',
  excluded: 'var(--na)',
}

/** A short note under a number, coloured by `tone` (better / worse / inline / muted). */
export interface Note { text: string; tone: string }

type HealthLatest = Ambient['health_latest']

/** Garmin's normal HRV range for this person, if it has one yet. */
export function hrvBand(h: HealthLatest): [number, number] | null {
  return h.hrv_baseline_low && h.hrv_baseline_high ? [h.hrv_baseline_low, h.hrv_baseline_high] : null
}

export function bodyBatteryNote(bb: number | null | undefined): Note | null {
  if (bb == null) return null
  return { text: bb >= 85 ? 'Full' : bb >= 60 ? 'Good' : 'Low', tone: bb >= 60 ? 'better' : 'worse' }
}

/** A run's average pace ("5:07/km"); null for other sports or without distance and time. */
export function runPace(s: Pick<Session, 'sport' | 'distance_m' | 'duration_s'>): string | null {
  return s.sport === 'running' && s.distance_m && s.duration_s ? `${pace(s.distance_m / s.duration_s)}/km` : null
}

/** This week's load against the sweet spot, plus a one-line hint (same wording as the wall). */
export function sweetHint(a: Ambient): string {
  const ss = a.sweet_spot
  if (!ss) return ''
  const w = a.today_workout
  const planned = w && !w.done ? w.est_load ?? 0 : 0
  if (ss.load >= ss.high) return 'Above the sweet spot — take it easy.'
  if (ss.load >= ss.low) return 'In the sweet spot. Nice.'
  if (planned && ss.load + planned >= ss.low) return `Today’s ${w!.title} gets you there.`
  return `~${Math.round((ss.low - ss.load) / 10) * 10} more to the sweet spot.`
}

/** A recent activity counts as fresh (hero card on Today) for 12 hours, like the wall's takeover window. */
export const FRESH_HOURS = 12
export function isFresh(iso: string): boolean {
  return Date.now() - new Date(iso).getTime() < FRESH_HOURS * 3600_000
}
