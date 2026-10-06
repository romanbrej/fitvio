import { Check, ChevronRight } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { Ambient } from '../../api'
import { SportIcon, VerdictPill } from '../../components/icons'
import { StatusMark, shortDuration } from '../../components/WeekStrip'
import { WorkoutShape } from '../../components/WorkoutShape'
import { SPORT_LABEL } from '../../format'
import { isEasy, minutes, phraseLabel, stepKindLabel, stepLength, stepLook, targetText } from '../../mission'
import { dayLabel, formAfter, localIso, readyLines, workoutFor } from '../../views/PlanDetail'
import { planName } from '../../views/WallAmbient'
import { usePhone } from '../ctx'
import { Card } from '../parts'

function Impact({ a, load }: { a: Ambient; load: number | null }) {
  const ss = a.sweet_spot
  const s = a.streak
  const after = ss && load != null ? ss.load + load : null
  return (
    <div className="ph-grid3">
      {after != null && ss && (
        <div className="ph-tile">
          <span className="ph-label sm">Week load</span>
          <b className="num">{ss.load} → {after}</b>
          <span className="ph-caption">{after > ss.high ? 'above the sweet spot' : after >= ss.low ? 'in the sweet spot' : `of ${ss.low}–${ss.high}`}</span>
        </div>
      )}
      <div className="ph-tile">
        <span className="ph-label sm">Streak</span>
        <b className="num" style={{ color: 'var(--accent-2)' }}>{Math.min(s.this_week + 1, s.min_sessions)} of {s.min_sessions}</b>
        <span className="ph-caption">{s.this_week + 1 >= s.min_sessions ? 'this week counts' : `${s.needed - 1} more after this`}</span>
      </div>
      {a.form && load != null && (
        <div className="ph-tile">
          <span className="ph-label sm">Form</span>
          <b className="num" style={{ color: 'var(--form)' }}>{Math.round(a.form.form)} → {Math.round(formAfter(a, load))}</b>
          <span className="ph-caption">tomorrow, roughly</span>
        </div>
      )}
    </div>
  )
}

export function Plan() {
  const { ambient } = usePhone()
  const a = ambient!
  const pw = a.plan_week ?? null
  const p = pw?.plan ?? a.today_workout?.plan ?? null
  const today = localIso()
  const [params, setParams] = useSearchParams()
  const asked = params.get('day')
  const selected = asked && /^\d{4}-\d{2}-\d{2}$/.test(asked) ? asked : today
  const { w, status } = workoutFor(a, selected, today)
  const isToday = selected === today
  const ready = readyLines(a)
  const strip = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // keep the chosen day's card in view in the sideways strip
    strip.current?.querySelector<HTMLElement>('[aria-pressed="true"]')?.scrollIntoView({ block: 'nearest', inline: 'center' })
  }, [selected])

  return (
    <div className="ph-stack">
      <header className="ph-section" style={{ gap: 6 }}>
        <span className="ph-label">{p ? 'Garmin Coach' : 'Garmin Connect calendar'}</span>
        <h1 className="ph-title">{p ? planName(p.name) : 'This week'}</h1>
        {p?.week && p.weeks ? (
          <div className="ph-row" aria-label={`Week ${p.week} of ${p.weeks}`}>
            <span className="ph-secondary">Week <b className="num">{p.week}</b> of <b className="num">{p.weeks}</b></span>
            <div className="ph-progress"><i style={{ width: `${Math.round(p.week / p.weeks * 100)}%` }} /></div>
          </div>
        ) : pw ? <span className="ph-secondary">{pw.done} of {pw.due} done so far</span> : null}
      </header>

      {pw && (
        <div ref={strip} className="ph-days" role="group" aria-label="The week">
          {pw.days.map(d => (
            <button key={d.day} className={`ph-daycard st-${d.status}`} aria-pressed={d.day === selected}
                    onClick={() => setParams(d.day === today ? {} : { day: d.day }, { replace: true })}>
              <span className="ph-row" style={{ justifyContent: 'space-between' }}>
                <span className="ph-label sm">{dayLabel(d.day).split(' ').slice(0, 2).join(' ')}</span>
                <StatusMark status={d.status} size={18} />
              </span>
              <span className="ph-daycard-title">{d.title ?? 'Rest'}</span>
              <span className="ph-caption num">{d.status === 'rest' ? 'recover' : shortDuration(d.est_duration_s)}</span>
            </button>
          ))}
        </div>
      )}

      {!w ? (
        <Card>
          <span className="ph-label">{isToday ? 'Today' : dayLabel(selected)}</span>
          <span className="ph-h2">{isToday ? 'Nothing planned — a rest day.' : 'Rest day — recover.'}</span>
        </Card>
      ) : (
        <>
          <Card>
            <div className="ph-row">
              <SportIcon sport={w.sport} size={18} color="var(--run)" />
              <span className="ph-label sm">{dayLabel(w.day)} · {SPORT_LABEL[w.sport]}</span>
              {w.est_load != null && <span className="ph-right ph-caption num">~{w.est_load} TRIMP</span>}
            </div>
            <span className="ph-h2">{w.title}{w.est_duration_s ? ` · ${minutes(w.est_duration_s)}` : ''}</span>
            {phraseLabel(w.phrase) && <span className="ph-foot">{phraseLabel(w.phrase)}{w.description ? ` · ${w.description}` : ''}</span>}
            {w.steps.length > 0 && <WorkoutShape steps={w.steps} height={64} easy={isEasy(w.phrase)} />}
            {w.steps.length > 0 && (
              <div>
                {w.steps.map((x, i) => (
                  <div key={i} className="ph-step">
                    <i style={{ background: stepLook(x, isEasy(w.phrase)).color }} />
                    <div className="ph-grow"><span className="ph-strong">{stepKindLabel(x.kind)}</span>
                      <span className="ph-foot num" style={{ color: x.kind === 'interval' ? 'var(--volt)' : undefined }}>{targetText(x) ?? 'easy'}</span></div>
                    <span className="num">{stepLength(x)}</span>
                  </div>
                ))}
              </div>
            )}
            {status === 'missed' && <span className="pill tone-worse">Missed</span>}
          </Card>

          {w.done && (
            <Link to={`/session/${encodeURIComponent(w.done.session_id)}`} className="ph-card ph-last">
              <span className="done-check"><Check size={18} strokeWidth={3} aria-hidden /></span>
              <div className="ph-grow"><span className="ph-strong ph-ellipsis">Done · {w.done.name ?? w.title}</span>
                <span className="ph-foot">{w.done.targets ? `${w.done.targets.hit}/${w.done.targets.of} blocks on target` : w.done.headline ?? 'Done'}</span></div>
              {w.done.verdict && <VerdictPill verdict={w.done.verdict} />}
              <ChevronRight size={18} color="var(--faint)" aria-hidden />
            </Link>
          )}

          {isToday && !w.done && (
            <Card>
              <span className="ph-label">Ready for it?</span>
              <span className="ph-h3" style={{ color: ready.ok ? 'var(--better)' : 'var(--warn)' }}>{ready.title}</span>
              <ul className="ph-reasons small">{ready.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
              <span className="ph-label" style={{ marginTop: 8 }}>What it does for you</span>
              <Impact a={a} load={w.est_load} />
            </Card>
          )}
        </>
      )}
      <span className="ph-caption" style={{ padding: '0 4px' }}>Garmin Coach plans about a week ahead.</span>
    </div>
  )
}
