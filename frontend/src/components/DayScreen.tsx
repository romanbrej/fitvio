import { useEffect, useState } from 'react'
import type { Ambient } from '../api'
import { headline, minutes, phraseLabel, READINESS_LEVEL, feedbackText } from '../mission'
import { Buddy } from './Buddy'
import './DayScreen.css'

/** How far the content drifts (px) — a new spot every minute so nothing burns into the panel. */
const DRIFT = 14

/** Daytime always-on screen: after a minute without a tap the overview fades to this calm view
 *  (clock, today's headline, a few facts, the pet). Any tap brings the overview back. */
export function DayScreen({ ambient: a, onWake }: { ambient: Ambient; onWake: () => void }) {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 15000)
    return () => clearInterval(t)
  }, [])
  const minute = now.getHours() * 60 + now.getMinutes()
  const dx = Math.round(Math.sin(minute * 1.7) * DRIFT)
  const dy = Math.round(Math.cos(minute * 1.3) * DRIFT)

  const h = headline(a)
  const w = a.today_workout
  const next = a.upcoming?.[0]
  const r = a.readiness
  const s = a.streak
  const ss = a.sweet_spot
  const facts: { k: string; v: string; sub: string; c: string }[] = []
  if (w) {
    facts.push(w.done
      ? { k: 'Today', v: `${w.title} ✓`, sub: w.done.headline ?? 'done', c: 'var(--volt)' }
      : { k: 'Today', v: `${w.title}${w.est_duration_s ? ` · ${minutes(w.est_duration_s)}` : ''}`,
          sub: [phraseLabel(w.phrase), w.est_load != null ? `load ~${w.est_load}` : null].filter(Boolean).join(' · '), c: 'var(--volt)' })
  } else if (next) {
    const day = new Date(`${next.day}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'long' })
    facts.push({ k: 'Next', v: next.title, sub: `${day}${next.est_duration_s ? ` · ${minutes(next.est_duration_s)}` : ''}`, c: 'var(--volt)' })
  }
  if (r) facts.push({ k: r.source === 'fitvio' ? 'Readiness · est.' : 'Readiness', v: `${r.score} · ${READINESS_LEVEL[r.level ?? ''] ?? r.level ?? ''}`, sub: feedbackText(r.feedback) ?? '', c: 'var(--better)' })
  if (s) facts.push({ k: 'Week streak', v: `${s.weeks} week${s.weeks === 1 ? '' : 's'}`,
                      sub: `${Math.min(s.this_week, s.min_sessions)} of ${s.min_sessions} workouts`, c: 'var(--accent-2)' })
  if (ss) facts.push({ k: 'This week', v: `${ss.load} TRIMP`, sub: `sweet spot ${ss.low}–${ss.high}`, c: 'var(--fitness)' })

  return (
    <button className="day-screen" onClick={onWake} aria-label="Wake the wall">
      <div className="day-inner" style={{ transform: `translate(${dx}px, ${dy}px)` }}>
        <div className="day-left">
          <div className="day-date">{now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}</div>
          <div className="day-clock num">{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}</div>
          <div className="day-headline">{h.title}</div>
          <ul className="day-facts">
            {facts.map(f => (
              <li key={f.k}>
                <i style={{ background: f.c }} />
                <span className="k">{f.k}</span>
                <span className="v">{f.v}</span>
                <span className="sub">{f.sub}</span>
              </li>
            ))}
          </ul>
          <div className="day-hint">Tap anywhere to wake</div>
        </div>
        {a.buddy && (
          <div className="day-pet">
            <div className="day-says">{a.buddy.line}</div>
            <Buddy animal={a.buddy.animal} mood={a.buddy.mood} size={280} />
          </div>
        )}
      </div>
    </button>
  )
}
