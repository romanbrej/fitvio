import { Flame } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Ambient } from '../api'
import { minutes } from '../mission'
import { Buddy } from './Buddy'
import './NightScreen.css'

/** 22:00–06:30: a dark, calm screen instead of the dashboard. A tap wakes the wall for 2 minutes. */
export function NightScreen({ ambient, onWake }: { ambient: Ambient | null; onWake: () => void }) {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 15000)
    return () => clearInterval(t)
  }, [])
  const s = ambient?.streak
  const ss = ambient?.sweet_spot
  const tomorrow = ambient?.upcoming?.find(u => {
    // after midnight "tomorrow" is today's date
    const d = new Date(now); d.setDate(d.getDate() + (now.getHours() < 12 ? 0 : 1))
    const local = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    return u.day === local
  })
  return (
    <button className="night-screen" onClick={onWake} aria-label="Wake display">
      <span className="night-clock num">{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}</span>
      <span className="night-msg">{tomorrow ? `Recover. Tomorrow: ${tomorrow.title}.` : 'Recover. Tomorrow we go again.'}</span>
      <span className="night-facts">
        {s && <span><Flame size={26} /> {s.weeks}-week streak · {Math.min(s.this_week, s.min_sessions)} of {s.min_sessions} this week</span>}
        {ss && <span>Weekly load {ss.load} · {ss.load >= ss.low ? (ss.load > ss.high ? 'above the sweet spot' : 'in the sweet spot') : `${ss.low - ss.load} to the sweet spot`}</span>}
        {tomorrow?.est_duration_s && <span>{minutes(tomorrow.est_duration_s)} planned</span>}
      </span>
      <span className="night-hint">Tap to wake for 2 minutes</span>
      {ambient?.buddy && <span className="night-buddy"><Buddy animal={ambient.buddy.animal} mood="asleep" size={190} /></span>}
    </button>
  )
}
