import { Check, ChevronRight, X } from 'lucide-react'
import type { PlanDay, PlanStatus, PlanWeek, PlannedWorkout } from '../api'
import { isEasy, minutes, workoutSummary } from '../mission'
import { WorkoutShape } from './WorkoutShape'

const WEEKDAY = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']

const STATUS_LABEL: Record<PlanStatus, string> = {
  done: 'done', missed: 'missed', today: 'today', planned: 'planned', rest: 'rest day',
}

export function weekday(iso: string): string {
  return WEEKDAY[new Date(`${iso}T12:00:00`).getDay()]
}

/** "45′" or "1:30" — short enough for a strip cell. */
export function shortDuration(sec: number | null | undefined): string {
  if (!sec) return ''
  const m = Math.round(sec / 60)
  return m >= 90 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}` : `${m}′`
}

export function StatusMark({ status, size = 22 }: { status: PlanStatus; size?: number }) {
  return (
    <span className={`plan-mark st-${status}`} style={{ width: size, height: size }} aria-hidden>
      {status === 'done' && <Check size={size * 0.65} strokeWidth={3.2} />}
      {status === 'missed' && <X size={size * 0.62} strokeWidth={3} />}
      {status === 'rest' && '–'}
    </span>
  )
}

function Cell({ d, onOpen }: { d: PlanDay; onOpen: () => void }) {
  return (
    <button className={`ws-cell st-${d.status}`} onClick={onOpen}
      aria-label={`${weekday(d.day)} ${d.title ?? ''} ${STATUS_LABEL[d.status]}`}>
      <span className="ws-day">{weekday(d.day)}</span>
      <StatusMark status={d.status} />
      <span className="ws-shape">{d.steps?.length ? <WorkoutShape steps={d.steps} height={20} easy={isEasy(d.phrase)} /> : null}</span>
      <span className="ws-dur num">{d.status === 'rest' ? '' : shortDuration(d.est_duration_s)}</span>
    </button>
  )
}

function TodayCell({ d, onOpen }: { d: PlanDay; onOpen: () => void }) {
  const summary = workoutSummary({ steps: d.steps ?? [] } as PlannedWorkout)
  return (
    <button className="ws-cell st-today wide" onClick={onOpen} aria-label={`Today ${d.title ?? ''}: open the plan`}>
      <div className="ws-today-head">
        <span className="ws-day">Today</span>
        <span className="link">Plan <ChevronRight size={15} /></span>
      </div>
      <span className="ws-title">{d.title}{d.est_duration_s ? ` · ${minutes(d.est_duration_s)}` : ''}</span>
      {d.steps?.length ? <WorkoutShape steps={d.steps} height={24} easy={isEasy(d.phrase)} /> : null}
      {summary.length > 0 && <span className="ws-line">{summary.join(' · ')}</span>}
    </button>
  )
}

/** The plan's week inside Today's Mission: today wide while it's still to do, the other days small.
 *  Every day opens the plan page on that day. */
export function WeekStrip({ week, onOpen }: { week: PlanWeek; onOpen: (day: string) => void }) {
  return (
    <div
      className="week-strip"
      role="group"
      aria-label="Training plan this week"
      style={{ gridTemplateColumns: week.days.map(d => (d.status === 'today' ? 'minmax(0, 2.6fr)' : 'minmax(0, 1fr)')).join(' ') }}
    >
      {week.days.map(d => (d.status === 'today'
        ? <TodayCell key={d.day} d={d} onOpen={() => onOpen(d.day)} />
        : <Cell key={d.day} d={d} onOpen={() => onOpen(d.day)} />))}
    </div>
  )
}
