import type { PmcDay } from './api'

/** Training load per week (Monday start), the last `n` weeks, from the daily PMC rows. */
export function weeklyLoads(pmc: PmcDay[], n = 8): { week: string; load: number }[] {
  const byWeek = new Map<string, number>()
  for (const d of pmc) {
    const day = new Date(`${d.day}T12:00:00`)
    day.setDate(day.getDate() - ((day.getDay() + 6) % 7))
    const k = day.toISOString().slice(0, 10)
    byWeek.set(k, (byWeek.get(k) ?? 0) + d.load)
  }
  return [...byWeek.entries()].sort().slice(-n).map(([week, load]) => ({ week, load: Math.round(load) }))
}

/** Where a week's load sits against the sweet spot; this week is still running. */
export function weekState(load: number, low: number, high: number, now: boolean): { text: string; tone: string } {
  if (now) return { text: 'so far', tone: 'muted' }
  if (load < low) return { text: 'below the sweet spot', tone: 'muted' }
  if (load > high) return { text: 'above the sweet spot', tone: 'worse' }
  return { text: 'in the sweet spot', tone: 'better' }
}
