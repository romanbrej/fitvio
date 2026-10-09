import { Activity, ArrowRight, ChevronRight } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../../api'
import type { Session, Sport, SportTrend, VerdictKind } from '../../api'
import { PeriodChips } from '../../components/PeriodChips'
import { SportIcon, VerdictPill } from '../../components/icons'
import { distance, duration, SPORT_LABEL, TYPE_LABEL } from '../../format'
import { useFetch } from '../../useFetch'
import { keyMetric } from '../../views/SessionDetail'
import { SPORT_COLOR } from '../../views/WallAmbient'
import { paceStr } from '../../mission'
import { periodAnswer, TONE_BG, TONE_COLOR } from '../../periodAnswer'
import { daysFor, periodSince, periodText, useTrendPeriod } from '../../trendPeriod'
import { AxisChart, dateAxis, dayLabel, niceTicks } from '../Chart'
import { usePhone } from '../ctx'
import { Back, Card } from '../parts'
import { MAIN_SPORTS, runPace } from '../util'

const PAGE = 50
type Row = Session & { verdict: VerdictKind | null; headline: string | null }

/** What's been loaded per list, for this visit: back from a session the list is there at once, so the
 *  browser can put you back at the same spot. */
const listCache = new Map<string, { rows: Row[]; done: boolean }>()

function monthOf(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
}

function dayTime(iso: string): string {
  const d = new Date(iso)
  return `${d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric' })} · ${d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`
}

/** True when row `i` is the first of its month (newest first), so a month heading goes above it. */
function startsMonth(rows: Row[], i: number): boolean {
  return i === 0 || monthOf(rows[i].start_time) !== monthOf(rows[i - 1].start_time)
}

/** One session: when and what, name, distance · time · key number (pace for runs), its verdict. */
function HistoryRow({ s, withSportIcon }: { s: Row; withSportIcon: boolean }) {
  const metric = runPace(s) ?? keyMetric(s.sport, s.features ?? {})
  const facts = [s.distance_m ? distance(s.distance_m, s.sport) : null, duration(s.duration_s), metric !== '—' ? metric : null]
  return (
    <Link to={`/session/${encodeURIComponent(s.id)}`} className="ph-hrow">
      {withSportIcon && <SportIcon sport={s.sport} size={20} color={SPORT_COLOR[s.sport]} />}
      <div className="ph-grow">
        <span className="ph-foot">{dayTime(s.start_time)} · {TYPE_LABEL[s.session_type] ?? s.session_type}</span>
        <span className="ph-ellipsis">{s.name || SPORT_LABEL[s.sport]}</span>
        <span className="ph-foot num">{facts.filter(Boolean).join(' · ')}</span>
      </div>
      {s.verdict && <VerdictPill verdict={s.verdict} />}
      <ChevronRight size={18} color="var(--faint)" aria-hidden />
    </Link>
  )
}

/** The whole history, 50 at a time: the next page loads when the end of the list comes into view. */
function History({ user, sport, type, since, span, all, latest }: {
  user: string; sport?: Sport; type?: string; since?: string; span: string | null; all: boolean; latest?: string
}) {
  const key = `${user}:${sport ?? 'all'}:${type ?? ''}:${since ?? ''}:${latest ?? ''}`  // a new workout → load afresh
  const [rows, setRows] = useState<Row[]>(() => listCache.get(key)?.rows ?? [])
  const [done, setDone] = useState(() => listCache.get(key)?.done ?? false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  const loading = useRef(false)  // state lags a render: two triggers in one frame must not load the same page twice

  const loadMore = useCallback(async () => {
    if (loading.current || done) return
    loading.current = true
    setBusy(true)
    setFailed(false)
    try {
      const page = await api.sessions(user, sport, PAGE, { offset: rows.length, type, since })
      const next = [...rows, ...page]
      const last = page.length < PAGE
      listCache.set(key, { rows: next, done: last })
      setRows(next)
      if (last) setDone(true)
    } catch {
      setFailed(true)  // keep what's loaded; the button retries
    }
    loading.current = false
    setBusy(false)
  }, [done, user, sport, type, since, rows, key])

  useEffect(() => {
    const el = end.current
    if (!el || done || failed) return
    const io = new IntersectionObserver(es => { if (es[0].isIntersecting) loadMore() }, { rootMargin: '400px' })
    io.observe(el)
    return () => io.disconnect()
  }, [loadMore, done, failed])

  if (done && !rows.length) return <Card><span className="ph-secondary">{span ? `No sessions in the last ${span}.` : 'No sessions yet.'}</span></Card>
  return (
    <section className="ph-history">
      {rows.map((s, i) => (
        <div key={s.id}>
          {startsMonth(rows, i) && <h2 className="ph-month">{monthOf(s.start_time)}</h2>}
          <HistoryRow s={s} withSportIcon={all} />
        </div>
      ))}
      {!done && (
        <div ref={end} className="ph-history-end">
          {failed ? <span className="ph-foot tone-warn">Couldn’t load more.</span> : null}
          <button className="ph-btn sm" onClick={loadMore} disabled={busy}>{busy ? 'Loading…' : failed ? 'Try again' : 'Load more'}</button>
        </div>
      )}
      {done && rows.length > 0 && <span className="ph-caption ph-history-done">{span ? `That’s the last ${span}` : 'That’s all'} — {rows.length} sessions.</span>}
    </section>
  )
}

/** "Am I improving?" over the picked period (`days`): the answer in a sentence, a period ago → now with the change
 *  in the verdict's colour, then each session of it on a chart with the trend line (gym: each week). */
function PeriodCard({ sport, t, days }: { sport: Sport; t: SportTrend; days: number }) {
  const [pickedDay, setPickedDay] = useState<string | null>(null)
  const answer = periodAnswer(sport, t, days)
  const period = t.periods?.[String(days)]
  const all = period?.points ?? t.status?.points ?? []
  // strength: the server sends the weeks before the period too (what it compares with); show the period's own
  const pts = sport === 'strength' ? all.slice(-Math.max(4, Math.ceil(days / 7))) : all
  const keys = pts.map(p => p.day)
  const i = pickedDay == null ? null : keys.lastIndexOf(pickedDay)
  const at = i == null || i < 0 ? null : i
  const running = sport === 'running'
  const fmt = (v: number) => running ? paceStr(v) : sport === 'cycling' ? v.toFixed(2) : String(v)
  // running: faster is up, so the pace is drawn negated
  const flip = (v: number | null | undefined) => v == null ? null : running ? -v : v
  const vals = pts.map(p => flip(p.value)!)
  const trend = pts.map(p => flip(('trend' in p ? p.trend : null) as number | null))
  const { lo, hi, ticks } = niceTicks(sport === 'strength' ? [0, ...vals] : [...vals, ...trend],
                                      v => fmt(running ? -v : v), '', running ? 5 : sport === 'cycling' ? 0.05 : 1)
  const what = sport === 'strength' ? 'Sessions per week' : running ? 'Pace at your reference HR' : 'Power per heartbeat'
  const label = sport === 'strength' ? 'Sessions per week' : running ? `Pace at ${t.status?.ref_hr ?? '—'} bpm, heat-adjusted` : 'Power per heartbeat, heat-adjusted'
  return (
    <Card style={{ borderTop: `3px solid ${SPORT_COLOR[sport]}` }}>
      {answer && (
        <>
          <h2 className="ph-answer"><span style={{ color: TONE_COLOR[answer.tone] }}>{answer.word}</span> {answer.text}</h2>
          <div className="ph-compare">
            <div className="ph-compare-pair">
              <span><span className="ph-label sm">{answer.compare.thenLabel}</span><b className="num">{answer.compare.then}</b></span>
              <ArrowRight size={18} color="var(--muted)" aria-hidden />
              <span><span className="ph-label sm">{answer.compare.nowLabel}</span><b className="num" style={{ color: 'var(--volt)' }}>{answer.compare.now}</b></span>
            </div>
            <span className="ph-change num" style={{ color: TONE_COLOR[answer.tone], background: TONE_BG[answer.tone] }}>{answer.compare.change}</span>
          </div>
        </>
      )}
      <div className="ph-row">
        <span className="ph-caption">{label}{answer ? ` · ${answer.count}` : ''}</span>
        <span className={`ph-right ph-when${at != null ? ' on' : ''}`} aria-live="polite">
          {at == null ? (pts.length >= 2 ? 'Tap the chart' : '')
            : `${sport === 'strength' ? `Week of ${dayLabel(pts[at].day)}` : dayLabel(pts[at].day, true)} · ${fmt(pts[at].value)}`}
        </span>
      </div>
      {pts.length >= 2 && (
        <AxisChart n={pts.length} lo={lo} hi={hi} ticks={ticks} height={128}
                   lines={sport === 'strength' ? [] : [
                     { values: trend, color: 'var(--volt)', width: 1.6, dash: true },
                     { values: vals, color: SPORT_COLOR[sport], width: 2.4 },
                   ]}
                   bars={sport === 'strength' ? vals : undefined}
                   barColor={(k, sel) => sel == null || sel === k ? SPORT_COLOR[sport] : 'var(--border-2)'}
                   axis={dateAxis(keys, sport === 'strength' ? 'This week' : 'Newest')} label={`${what}, last ${periodText(days)}`}
                   picked={at} onPick={k => setPickedDay(k == null ? null : keys[k])} />
      )}
      <span className="ph-caption">{running
        ? 'Steady time at your reference HR in every outdoor run. Dashed: the trend. Up is faster.'
        : sport === 'cycling' ? 'Rides with power. Dashed: the trend.' : 'Compared with the same length before.'}</span>
    </Card>
  )
}

/** One sport's (or every activity's) whole history: its trend on top, type chips, then the sessions by month. */
export function SportHistory() {
  const { sport: param } = useParams()
  const { me, ambient } = usePhone()
  const [params, setParams] = useSearchParams()
  const [picked, pick] = useTrendPeriod()
  const all = param === 'all'
  const sport = MAIN_SPORTS.includes(param as Sport) ? param as Sport : undefined
  const type = params.get('type') ?? undefined
  const t = sport ? ambient?.trends[sport] : undefined
  // a sport page shows the picked period, card and list alike; "All activities" stays the whole history
  const days = sport ? daysFor(sport, picked) : null
  const since = sport && days ? periodSince(sport, t, days) : undefined
  const { data: types } = useFetch(() => api.sessionTypes(me.id, sport, since), [me.id, sport, since])
  if (!all && !sport) return <Navigate to="/trends" replace />
  const total = types?.reduce((n, x) => n + x.count, 0)
  // a type picked earlier that has no session in this period keeps its chip, so it can be switched off
  const chips = types && type && !types.some(x => x.type === type) ? [...types, { type, count: 0 }] : types
  const span = days ? periodText(days) : null

  return (
    <div className="ph-stack">
      <Back to="/trends" label="Trends" />
      <header className="ph-section" style={{ gap: 6 }}>
        <span className="ph-row" style={{ gap: 8 }}>
          {sport ? <SportIcon sport={sport} size={22} color={SPORT_COLOR[sport]} /> : <Activity size={22} color="var(--volt)" aria-hidden />}
          <span className="ph-label">{total != null ? `${total} sessions${span ? ` · last ${span}` : ''}` : 'History'}</span>
        </span>
        <h1 className="ph-title">{sport ? SPORT_LABEL[sport] : 'All activities'}</h1>
      </header>

      {sport && days && <PeriodChips days={days} onPick={pick} className="ph-chips" btnClass="ph-chip-btn" />}
      {sport && t && days && <PeriodCard sport={sport} t={t} days={days} />}

      {chips && (chips.length > 1 || type) && (
        <div className="ph-chips" role="group" aria-label="Session type">
          <button className="ph-chip-btn" aria-pressed={!type} onClick={() => setParams({}, { replace: true })}>All</button>
          {chips.map(x => (
            <button key={x.type} className="ph-chip-btn" aria-pressed={type === x.type}
                    onClick={() => setParams({ type: x.type }, { replace: true })}>
              {TYPE_LABEL[x.type] ?? x.type} <span className="num">{x.count}</span>
            </button>
          ))}
        </div>
      )}

      {/* a new workout shifts every page by one: start the list afresh rather than page on from stale rows */}
      <History key={`${param}:${type ?? ''}:${since ?? ''}:${ambient?.last_workout?.id ?? ''}`} user={me.id} sport={sport} type={type}
               since={since} span={span} all={all} latest={ambient?.last_workout?.id} />
    </div>
  )
}
