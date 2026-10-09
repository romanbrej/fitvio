import { useEffect, useState } from 'react'
import { api } from './api'
import type { Sport, SportTrend } from './api'

/** The lengths a person can look back over ("Am I improving?" over …), as the API sends them (wall.PERIOD_DAYS). */
export const PERIODS: { days: number; chip: string; text: string }[] = [
  { days: 14, chip: '2 wk', text: '2 wks' },
  { days: 28, chip: '4 wk', text: '4 wks' },
  { days: 42, chip: '6 wk', text: '6 wks' },
  { days: 56, chip: '8 wk', text: '8 wks' },
  { days: 91, chip: '3 mo', text: '3 months' },
  { days: 182, chip: '6 mo', text: '6 months' },
  { days: 365, chip: '1 yr', text: '12 months' },
]

/** Until someone picks one: the wall card's own length (wall.DEFAULT_DAYS). */
export const DEFAULT_DAYS: Partial<Record<Sport, number>> = { running: 42, cycling: 91, strength: 42 }

export function periodText(days: number): string {
  return PERIODS.find(p => p.days === days)?.text ?? `${days} days`
}

const EVENT = 'fitvio-trend-period'
/** Picks made on this page, per person, until the server's copy (ambient.trend_period) catches up. */
const picked = new Map<string, number>()

/** The period this person picked (one for every sport, kept on the server so it follows them to every
 *  device and the partner keeps theirs), or null for each sport's default. `saved`: ambient.trend_period. */
export function useTrendPeriod(user: string | undefined, saved: number | null | undefined): [number | null, (days: number) => void] {
  const [, rerender] = useState(0)
  useEffect(() => {
    const sync = () => rerender(n => n + 1)
    window.addEventListener(EVENT, sync)
    return () => window.removeEventListener(EVENT, sync)
  }, [])
  const pick = (days: number) => {
    if (!user) return
    const before = picked.get(user)
    picked.set(user, days)
    window.dispatchEvent(new Event(EVENT))
    api.setTrendPeriod(user, days).catch(() => {  // refused (not at home) or offline: back to what was saved
      if (before == null) picked.delete(user)
      else picked.set(user, before)
      window.dispatchEvent(new Event(EVENT))
    })
  }
  // once the server's copy has it, it's the one to follow (a pick on another device shows on the next refresh)
  useEffect(() => { if (user && saved != null && picked.get(user) === saved) picked.delete(user) }, [user, saved])
  const days = (user ? picked.get(user) : undefined) ?? saved ?? null
  return [PERIODS.some(p => p.days === days) ? days : null, pick]
}

export function daysFor(sport: Sport, picked: number | null): number {
  return picked ?? DEFAULT_DAYS[sport] ?? 42
}


/** The first day of a period, as YYYY-MM-DD: counted back from the newest session of the sport, so "4 wk"
 *  lists the last four weeks of it (from today for the gym, which counts how often you go). */
export function periodSince(sport: Sport, t: SportTrend | undefined, days: number, today = new Date()): string {
  const end = sport !== 'strength' && t?.last_time ? new Date(t.last_time) : today
  const d = new Date(end.getFullYear(), end.getMonth(), end.getDate() - days, 12)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
