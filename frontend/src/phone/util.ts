import type { Ambient, VerdictKind } from '../api'

/** The verdict's colour: Better gets the volt accent, like on the wall. Always shown with its icon and word. */
export const VERDICT_COLOR: Record<VerdictKind, string> = {
  better: 'var(--volt)', in_line: 'var(--inline)', worse: 'var(--worse)', not_comparable: 'var(--na)', load_only: 'var(--load)',
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
