import { Activity, ChevronRight } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../../api'
import type { Session, Sport, VerdictKind } from '../../api'
import { SportIcon, VerdictPill } from '../../components/icons'
import { Sparkline } from '../../components/Sparkline'
import { distance, duration, pace, SPORT_LABEL, TYPE_LABEL } from '../../format'
import { useFetch } from '../../useFetch'
import { keyMetric } from '../../views/SessionDetail'
import { SPORT_COLOR, tileContent } from '../../views/WallAmbient'
import { usePhone } from '../ctx'
import { Back, Card } from '../parts'

const PAGE = 50
const SPORTS: Sport[] = ['running', 'cycling', 'swimming', 'strength']
type Row = Session & { verdict: VerdictKind | null; headline: string | null }

/** What's been loaded per list, for this visit: back from a session the list is there at once, so the
 *  browser can put you back at the same spot. */
const loaded = new Map<string, { rows: Row[]; done: boolean }>()

function monthOf(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
}

function dayTime(iso: string): string {
  const d = new Date(iso)
  return `${d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric' })} · ${d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`
}

/** The whole history, 50 at a time: the next page loads when the end of the list comes into view. */
function History({ user, sport, type, all, latest }: { user: string; sport?: Sport; type?: string; all: boolean; latest?: string }) {
  const key = `${user}:${sport ?? 'all'}:${type ?? ''}:${latest ?? ''}`  // a new workout → load afresh
  const [rows, setRows] = useState<Row[]>(() => loaded.get(key)?.rows ?? [])
  const [done, setDone] = useState(() => loaded.get(key)?.done ?? false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const end = useRef<HTMLDivElement>(null)

  const more = useCallback(async () => {
    if (busy || done) return
    setBusy(true)
    setFailed(false)
    try {
      const page = await api.sessions(user, sport, PAGE, { offset: rows.length, type })
      const next = [...rows, ...page]
      const last = page.length < PAGE
      loaded.set(key, { rows: next, done: last })
      setRows(next)
      if (last) setDone(true)
    } catch {
      setFailed(true)  // keep what's loaded; the button retries
    }
    setBusy(false)
  }, [busy, done, user, sport, type, rows, key])

  useEffect(() => {
    const el = end.current
    if (!el || done || failed) return
    const io = new IntersectionObserver(es => { if (es[0].isIntersecting) more() }, { rootMargin: '400px' })
    io.observe(el)
    return () => io.disconnect()
  }, [more, done, failed])

  if (done && !rows.length) return <Card><span className="ph-secondary">No sessions yet.</span></Card>
  return (
    <section className="ph-history">
      {rows.map((s, i) => {
        const m = monthOf(s.start_time)
        const head = i === 0 || m !== monthOf(rows[i - 1].start_time)
        // runs: the pace says more than the efficiency number; other sports: their key metric
        const metric = s.sport === 'running' && s.distance_m && s.duration_s ? `${pace(s.distance_m / s.duration_s)}/km`
          : keyMetric(s.sport, s.features ?? {})
        return (
          <div key={s.id}>
            {head && <h2 className="ph-month">{m}</h2>}
            <Link to={`/session/${encodeURIComponent(s.id)}`} className="ph-hrow">
              {all && <SportIcon sport={s.sport} size={20} color={SPORT_COLOR[s.sport]} />}
              <div className="ph-grow">
                <span className="ph-foot">{dayTime(s.start_time)} · {TYPE_LABEL[s.session_type] ?? s.session_type}</span>
                <span className="ph-ellipsis">{s.name || SPORT_LABEL[s.sport]}</span>
                <span className="ph-foot num">{[s.distance_m ? distance(s.distance_m, s.sport) : null, duration(s.duration_s),
                  metric !== '—' ? metric : null].filter(Boolean).join(' · ')}</span>
              </div>
              {s.verdict && <VerdictPill verdict={s.verdict} />}
              <ChevronRight size={18} color="var(--faint)" aria-hidden />
            </Link>
          </div>
        )
      })}
      {!done && (
        <div ref={end} className="ph-history-end">
          {failed ? <span className="ph-foot tone-warn">Couldn’t load more.</span> : null}
          <button className="ph-btn sm" onClick={more} disabled={busy}>{busy ? 'Loading…' : failed ? 'Try again' : 'Load more'}</button>
        </div>
      )}
      {done && rows.length > 0 && <span className="ph-caption ph-history-done">That’s all — {rows.length} sessions.</span>}
    </section>
  )
}

/** One sport's (or every activity's) whole history: its trend on top, type chips, then the sessions by month. */
export function SportHistory() {
  const { sport: param } = useParams()
  const { me, ambient } = usePhone()
  const [params, setParams] = useSearchParams()
  const all = param === 'all'
  const sport = SPORTS.includes(param as Sport) ? param as Sport : undefined
  const type = params.get('type') ?? undefined
  const { data: types } = useFetch(() => api.sessionTypes(me.id, sport), [me.id, sport])
  if (!all && !sport) return <Navigate to="/trends" replace />
  const t = sport ? ambient?.trends[sport] : undefined
  const c = sport && t ? tileContent(sport, t) : null
  const total = types?.reduce((n, x) => n + x.count, 0)

  return (
    <div className="ph-stack">
      <Back to="/trends" label="Trends" />
      <header className="ph-section" style={{ gap: 6 }}>
        <span className="ph-row" style={{ gap: 8 }}>
          {sport ? <SportIcon sport={sport} size={22} color={SPORT_COLOR[sport]} /> : <Activity size={22} color="var(--volt)" aria-hidden />}
          <span className="ph-label">{total != null ? `${total} sessions` : 'History'}</span>
        </span>
        <h1 className="ph-title">{sport ? SPORT_LABEL[sport] : 'All activities'}</h1>
      </header>

      {c && (
        <Card style={{ borderTop: `3px solid ${SPORT_COLOR[sport!]}` }}>
          <div className="ph-row" style={{ alignItems: 'flex-end' }}>
            <div className="ph-grow">
              <span><b className="ph-sport-big">{c.big}</b>{c.unit && <span className="ph-unit"> {c.unit}</span>}</span>
              <span className="ph-caption">{c.caption}</span>
            </div>
            <div style={{ width: 120 }}><Sparkline values={c.spark} height={44} color={SPORT_COLOR[sport!]} /></div>
          </div>
        </Card>
      )}

      {types && types.length > 1 && (
        <div className="ph-chips" role="group" aria-label="Session type">
          <button className="ph-chip-btn" aria-pressed={!type} onClick={() => setParams({}, { replace: true })}>All</button>
          {types.map(x => (
            <button key={x.type} className="ph-chip-btn" aria-pressed={type === x.type}
                    onClick={() => setParams({ type: x.type }, { replace: true })}>
              {TYPE_LABEL[x.type] ?? x.type} <span className="num">{x.count}</span>
            </button>
          ))}
        </div>
      )}

      <History key={`${param}:${type ?? ''}`} user={me.id} sport={sport} type={type} all={all} latest={ambient?.last_workout?.id} />
    </div>
  )
}
