import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Ambient, Sport } from '../../api'
import { SportIcon, VerdictPill } from '../../components/icons'
import { Sparkline } from '../../components/Sparkline'
import { formState, num, signed, SPORT_LABEL } from '../../format'
import { MiniPmc, SPORT_COLOR, tileContent } from '../../views/WallAmbient'
import { usePhone } from '../ctx'
import { Card, SweetBar } from '../parts'
import { sweetHint } from '../util'

const SPORTS: Sport[] = ['running', 'cycling', 'swimming', 'strength']

export function TrendsNav({ on }: { on: 'load' | 'health' }) {
  return (
    <nav className="ph-seg" aria-label="Trends sections">
      <Link to="/trends" aria-current={on === 'load' ? 'page' : undefined}>Load &amp; sports</Link>
      <Link to="/trends/health" aria-current={on === 'health' ? 'page' : undefined}>Health</Link>
    </nav>
  )
}

/** Training load per week (Monday start), the last `n` weeks, from the daily PMC rows. */
function weeklyLoads(a: Ambient, n = 8): { week: string; load: number }[] {
  const byWeek = new Map<string, number>()
  for (const d of a.pmc) {
    const day = new Date(`${d.day}T12:00:00`)
    day.setDate(day.getDate() - ((day.getDay() + 6) % 7))
    const k = day.toISOString().slice(0, 10)
    byWeek.set(k, (byWeek.get(k) ?? 0) + d.load)
  }
  return [...byWeek.entries()].sort().slice(-n).map(([week, load]) => ({ week, load: Math.round(load) }))
}

export function Trends() {
  const { ambient } = usePhone()
  const a = ambient!
  const f = a.form
  const fs = formState(f?.form)
  const ss = a.sweet_spot
  const weeks = weeklyLoads(a)
  const top = Math.max(1, ...weeks.map(w => w.load), ss?.high ?? 0)
  return (
    <div className="ph-stack">
      <h1 className="ph-title">Trends</h1>
      <TrendsNav on="load" />

      <Card>
        <div className="ph-row"><span className="ph-h3">Training load</span><span className="ph-right ph-caption">6 weeks</span></div>
        <div className="ph-grid3">
          <div><span className="ph-foot" style={{ color: 'var(--fitness)' }}>— Fitness</span><b className="num ph-v">{num(f?.fitness)}</b></div>
          <div><span className="ph-foot" style={{ color: 'var(--fatigue)' }}>- - Fatigue</span><b className="num ph-v">{num(f?.fatigue)}</b></div>
          <div><span className="ph-foot" style={{ color: 'var(--form)' }}>— Form</span><b className="num ph-v" style={{ color: 'var(--form)' }}>{signed(f?.form, 0)}</b>
            <span className={`ph-caption tone-${fs.tone}`}>{fs.label.split(' — ')[0]}</span></div>
        </div>
        <div className="ph-pmc"><MiniPmc days={a.pmc.slice(-42)} /></div>
        <div className="ph-axis"><span>6 weeks ago</span><span>today</span></div>
        <span className="ph-caption">Fitness is your 6-week training, fatigue the last week; form = fitness − fatigue. Above zero you’re fresh.</span>
      </Card>

      {ss && (
        <Card>
          <div className="ph-row"><span className="ph-label">This week · TRIMP</span>
            <span className="ph-right"><b className="num ph-v">{ss.load}</b> <span className="num ph-unit">/ {ss.low}–{ss.high}</span></span></div>
          <SweetBar a={a} height={14} />
          <div className="ph-axis"><span>too little</span><span>sweet spot</span><span>too much</span></div>
          <span className="ph-secondary">{sweetHint(a)}</span>
          <div className="ph-bars" aria-label="Load per week, last 8 weeks">
            {weeks.map((w, i) => (
              <div key={w.week} className={i === weeks.length - 1 ? 'now' : ''}>
                <i style={{ height: `${Math.max(3, w.load / top * 100)}%` }} />
                <span className="num">{i === weeks.length - 1 ? 'now' : w.week.slice(5).replace('-', '/')}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <section className="ph-section">
        <span className="ph-label" style={{ padding: '0 4px' }}>Am I improving?</span>
        {SPORTS.map(sp => {
          const t = a.trends[sp]
          const c = t ? tileContent(sp, t) : null
          const inner = (
            <>
              <div className="ph-grow">
                <span className="ph-row" style={{ gap: 6 }}><SportIcon sport={sp} size={18} color={SPORT_COLOR[sp]} /><span className="ph-label sm" style={{ color: 'var(--text-2)' }}>{SPORT_LABEL[sp]}</span></span>
                {c ? <>
                  <span><b className="ph-sport-big">{c.big}</b>{c.unit && <span className="ph-unit"> {c.unit}</span>}</span>
                  <span className="ph-caption">{c.caption}</span>
                  {c.extra && <span className="ph-caption">{c.extra}</span>}
                </> : <span className="ph-caption">No sessions yet</span>}
              </div>
              {c && (
                <div className="ph-trend-side">
                  <Sparkline values={c.spark} height={40} color={SPORT_COLOR[sp]} />
                  <VerdictPill verdict={t!.last_verdict} />
                </div>
              )}
            </>
          )
          const style = { borderTopColor: SPORT_COLOR[sp] }
          return t
            ? <Link key={sp} to={`/session/${encodeURIComponent(t.last_session)}`} className="ph-card ph-sport-row" style={style}
                    aria-label={`${SPORT_LABEL[sp]} — open the last session`}>{inner}<ChevronRight size={18} color="var(--faint)" aria-hidden /></Link>
            : <div key={sp} className="ph-card ph-sport-row" style={style}>{inner}</div>
        })}
      </section>
    </div>
  )
}
