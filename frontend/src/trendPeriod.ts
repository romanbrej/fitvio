import { useEffect, useState } from 'react'
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

const KEY = 'fitvio.trendPeriod'
const EVENT = 'fitvio-trend-period'

function stored(): number | null {
  try {
    const v = Number(localStorage.getItem(KEY))
    return PERIODS.some(p => p.days === v) ? v : null
  } catch {
    return null  // private window, blocked storage: the defaults
  }
}

/** The period picked on this device (one for every sport), or null for each sport's default. */
export function useTrendPeriod(): [number | null, (days: number) => void] {
  const [days, setDays] = useState<number | null>(stored)
  useEffect(() => {
    const sync = () => setDays(stored())
    window.addEventListener(EVENT, sync)
    window.addEventListener('storage', sync)
    return () => { window.removeEventListener(EVENT, sync); window.removeEventListener('storage', sync) }
  }, [])
  const pick = (d: number) => {
    try { localStorage.setItem(KEY, String(d)) } catch { /* kept for this page only */ }
    setDays(d)
    window.dispatchEvent(new Event(EVENT))
  }
  return [days, pick]
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
