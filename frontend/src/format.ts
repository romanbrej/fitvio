import type { Sport, VerdictKind } from './api'

export function duration(s: number | null | undefined): string {
  if (!s) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.round(s % 60)
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}

export function hoursMinutes(min: number | null | undefined): string {
  if (min == null) return '—'
  return `${Math.floor(min / 60)}h ${String(Math.round(min % 60)).padStart(2, '0')}m`
}

export function distance(m: number | null | undefined, sport?: Sport): string {
  if (!m) return '—'
  if (sport === 'swimming') return `${Math.round(m)} m`
  return `${(m / 1000).toFixed(m >= 10000 ? 1 : 2)} km`
}

export function pace(speed: number | null | undefined): string {
  if (!speed || speed <= 0) return '—'
  const s = 1000 / speed
  return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`
}

export function kmh(speed: number | null | undefined): string {
  return speed ? (speed * 3.6).toFixed(1) : '—'
}

export function num(v: number | null | undefined, dp = 0): string {
  return v == null ? '—' : v.toFixed(dp)
}

export function signed(v: number | null | undefined, dp = 1, unit = ''): string {
  if (v == null) return '—'
  const r = Number(v.toFixed(dp))
  return `${r > 0 ? '+' : r < 0 ? '−' : '±'}${Math.abs(r).toFixed(dp)}${unit}`
}

export function when(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const y = new Date(); y.setDate(today.getDate() - 1)
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  if (d.toDateString() === today.toDateString()) return `Today ${time}`
  if (d.toDateString() === y.toDateString()) return `Yesterday ${time}`
  return `${d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })} ${time}`
}

export function shortDay(iso: string): string {
  return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' })
}

export function ago(iso: string | null): string {
  if (!iso) return 'never'
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const h = Math.round(mins / 60)
  if (h < 48) return `${h} h ago`
  return `${Math.round(h / 24)} days ago`
}

export const VERDICT_LABEL: Record<VerdictKind, string> = {
  better: 'Better', in_line: 'In line', worse: 'Worse', not_comparable: 'Not comparable', load_only: 'Logged',
  excluded: 'Excluded',
}

export const SPORT_LABEL: Record<Sport, string> = {
  running: 'Running', cycling: 'Cycling', swimming: 'Swimming', strength: 'Gym', other: 'Other',
}

export const TYPE_LABEL: Record<string, string> = {
  easy: 'Easy', long: 'Long', tempo: 'Tempo', intervals: 'Intervals', race: 'Race', strength: 'Strength', other: 'Activity',
}

/** Classic form (TSB) bands. */
export function formState(form: number | null | undefined): { label: string; tone: string } {
  if (form == null) return { label: '—', tone: 'muted' }
  if (form > 25) return { label: 'Very fresh — losing fitness', tone: 'warn' }
  if (form > 5) return { label: 'Fresh', tone: 'better' }
  if (form > -10) return { label: 'Neutral', tone: 'inline' }
  if (form > -30) return { label: 'Productive training', tone: 'better' }
  return { label: 'Overreaching risk', tone: 'worse' }
}

export function feelLabel(feel: number | null | undefined): string {
  if (feel == null) return '—'
  if (feel >= 100) return 'Very strong'
  if (feel >= 75) return 'Strong'
  if (feel >= 50) return 'Normal'
  if (feel >= 25) return 'Weak'
  return 'Very weak'
}

/** Where a session's weather came from (as fitvio/weather.py `label`): "Open-Meteo", "Garmin station Town", "Intervals.icu". */
export function weatherSource(w: { source?: string; station?: string } | null | undefined): string | null {
  if (!w) return null
  if (w.source === 'Garmin' || (w.station && !w.source)) return w.station ? `Garmin station ${w.station}` : 'Garmin'
  return w.source ?? null
}
