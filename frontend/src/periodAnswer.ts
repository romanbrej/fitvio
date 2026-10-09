import type { Sport, SportTrend } from './api'
import { paceStr } from './mission'
import { periodText } from './trendPeriod'
import { tileContent } from './views/WallAmbient'

export interface PeriodAnswer {
  word: string; text: string; tone: 'better' | 'inline' | 'worse' | 'muted'
  /** the phone's one line: a period ago → now, and the change in the verdict's colour */
  compare: { thenLabel: string; then: string; nowLabel: string; now: string; change: string }
  /** what the chart counts: "10 runs", "4 rides", "6 sessions" */
  count: string
}

/** "Am I improving?" over a period, the same on the wall and the phone: "Yes." + "24 s/km faster in 2 wks."
 *  and a period ago → now with the change, and how many sessions. Null without that period. */
export function periodAnswer(sport: Sport, t: SportTrend, days: number): PeriodAnswer | null {
  const p = t.periods?.[String(days)]
  if (!p) return null
  const c = tileContent(sport, t, undefined, days)
  const span = periodText(days)
  const word = c.tone === 'better' ? 'Yes.' : c.tone === 'worse' ? 'Not yet.' : c.tone === 'inline' ? 'Holding.' : 'Too few.'
  const ago = `${span} ago`
  if (sport === 'strength') {
    const n = p.n, prev = p.n_prev ?? 0
    const text = p.change != null ? (c.tone === 'inline' ? `e1RM steady over ${span}.` : `e1RM ${p.change > 0 ? 'up' : 'down'} ${Math.abs(p.change).toFixed(1)} % in ${span}.`)
      : c.tone === 'inline' ? `As often as the ${span} before.`
      : `${Math.abs(n - prev)} ${n > prev ? 'more' : 'fewer'} sessions than the ${span} before.`
    const e1rm = p.change == null ? null : `${p.change > 0 ? '+' : p.change < 0 ? '−' : '±'}${Math.abs(p.change).toFixed(1)} % e1RM`
    return { word: c.tone === 'muted' ? 'Too few.' : word, text, tone: c.tone, count: `${n} sessions`,
      compare: { thenLabel: `The ${span} before`, then: String(prev), nowLabel: 'Now · sessions', now: String(n),
                 change: e1rm ?? `${n - prev > 0 ? '+' : n - prev < 0 ? '−' : '±'}${Math.abs(n - prev)}` } }
  }
  const running = sport === 'running'
  const noun = running ? 'runs' : 'power rides'
  // running: count the change from the two paces as shown, so "5 s/km" always matches 4:58 → 4:53
  const shown = running && p.change != null && p.now != null && p.then != null
    ? Math.round(p.then) - Math.round(p.now) : p.change
  const text = p.change == null ? `Not enough ${noun} in ${span} for a trend.`
    : c.tone === 'inline' ? `Steady over ${span}.`
    : running ? `${Math.abs(shown!).toFixed(0)} s/km ${shown! > 0 ? 'faster' : 'slower'} in ${span}.`
    : `${Math.abs(p.change).toFixed(1)} % ${p.change > 0 ? 'more' : 'less'} power per beat in ${span}.`
  const fmt = (v: number | null | undefined) => v == null ? '—' : running ? paceStr(v) : v.toFixed(2)
  const unit = running ? '/km' : 'W/beat'
  const r = shown == null ? null : Number(shown.toFixed(running ? 0 : 1))
  const change = r == null ? '—' : running
    ? `${r > 0 ? '−' : r < 0 ? '+' : '±'}${Math.abs(r).toFixed(0)} s/km`  // faster = fewer seconds per km
    : `${r > 0 ? '+' : r < 0 ? '−' : '±'}${Math.abs(r).toFixed(1)} %`
  return { word, text, tone: c.tone, count: `${p.n} ${running ? 'runs' : 'rides'}`,
    compare: { thenLabel: `${ago} · ${unit}`, then: fmt(p.then), nowLabel: `Now · ${unit}`,
               now: fmt(p.now ?? (running ? null : t.status?.w_per_beat)), change } }
}

export const TONE_COLOR = { better: 'var(--better)', inline: 'var(--inline)', worse: 'var(--worse)', muted: 'var(--muted)' } as const
/** the chip behind a coloured change */
export const TONE_BG = { better: 'rgba(61, 220, 132, 0.14)', inline: 'rgba(56, 189, 248, 0.14)', worse: 'rgba(248, 113, 113, 0.14)', muted: 'var(--surface-3)' } as const
