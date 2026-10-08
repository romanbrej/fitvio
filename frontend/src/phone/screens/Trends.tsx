import { Activity, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Ambient } from '../../api'
import { SportIcon, TrendPill } from '../../components/icons'
import { Sparkline } from '../../components/Sparkline'
import { SPORT_LABEL } from '../../format'
import { SPORT_COLOR, tileContent } from '../../views/WallAmbient'
import { weekState, weeklyLoads } from '../../weeks'
import { AxisChart, dateAxis, dayLabel, niceTicks } from '../Chart'
import { usePhone } from '../ctx'
import { Card, FormNumbers, SweetBar } from '../parts'
import { MAIN_SPORTS, sweetHint } from '../util'

export function TrendsNav({ on }: { on: 'load' | 'health' }) {
  return (
    <nav className="ph-seg" aria-label="Trends sections">
      <Link to="/trends" aria-current={on === 'load' ? 'page' : undefined}>Load &amp; sports</Link>
      <Link to="/trends/health" aria-current={on === 'health' ? 'page' : undefined}>Health</Link>
    </nav>
  )
}

const SWEET_EDGE = '#a3c25a'

function LoadCard({ a }: { a: Ambient }) {
  const [picked, setPicked] = useState<number | null>(null)
  const days = a.pmc.slice(-42)
  if (days.length < 2) return null
  const d = picked == null ? a.form : days[picked]
  const { lo, hi, ticks } = niceTicks(days.flatMap(p => [p.fitness, p.fatigue, p.form, 0]), v => String(v))
  const when = picked == null ? '6 weeks' : picked === days.length - 1 ? 'Today' : dayLabel(days[picked].day, true)
  return (
    <Card>
      <div className="ph-row"><span className="ph-h3">Training load</span><span className={`ph-right ph-when${picked != null ? ' on' : ''}`}>{when}</span></div>
      <FormNumbers form={d} legend />
      <AxisChart n={days.length} lo={lo} hi={hi} ticks={ticks.map(t => t.value === 0 ? { ...t, ref: true } : t)} height={150}
                 lines={[
                   { values: days.map(p => p.fitness), color: 'var(--fitness)', width: 3, area: true },
                   { values: days.map(p => p.fatigue), color: 'var(--fatigue)', width: 1.8, dash: true },
                   { values: days.map(p => p.form), color: 'var(--form)' },
                 ]}
                 axis={dateAxis(days.map(p => p.day), 'Today')}
                 label="Training load, last 6 weeks" picked={picked} onPick={setPicked} />
      <span className="ph-caption">Fitness is your 6-week training, fatigue the last week; form = fitness − fatigue. Above the dashed 0 line you’re fresh.</span>
    </Card>
  )
}

function WeeksCard({ a }: { a: Ambient }) {
  const [picked, setPicked] = useState<number | null>(null)
  const ss = a.sweet_spot!
  const weeks = weeklyLoads(a.pmc)
  const n = weeks.length
  const hi = Math.ceil(Math.max(ss.high, ...weeks.map(w => w.load)) * 1.08 / 100) * 100
  const i = picked ?? n - 2
  const w = weeks[i]
  const state = w && weekState(w.load, ss.low, ss.high, i === n - 1)
  const title = i === n - 1 ? 'This week' : picked == null ? 'Last week' : `Week of ${dayLabel(w.week)}`
  return (
    <Card>
      <div className="ph-row"><span className="ph-label">This week · TRIMP</span>
        <span className="ph-right"><b className="num ph-v">{ss.load}</b> <span className="num ph-unit">/ {ss.low}–{ss.high}</span></span></div>
      <SweetBar a={a} height={14} />
      <div className="ph-axis"><span>too little</span><span>sweet spot</span><span>too much</span></div>
      <span className="ph-secondary">{sweetHint(a)}</span>
      {w && (
        <div className="ph-row ph-week-read">
          <span className="ph-label sm">{title}</span>
          <span className="ph-right"><b className="num">{w.load}</b> <span className={`ph-foot tone-${state.tone}`} style={{ display: 'inline' }}>{state.text}</span></span>
        </div>
      )}
      <AxisChart n={n} lo={0} hi={hi} height={120}
                 ticks={[{ value: 0, label: '0' }, { value: ss.low, label: String(ss.low), ref: true }, { value: ss.high, label: String(ss.high), ref: true }]}
                 band={[ss.low, ss.high]} bandColor="rgba(212, 255, 58, 0.08)" refColor={SWEET_EDGE}
                 bars={weeks.map(x => x.load)}
                 barColor={(k, p) => k === n - 1 ? (p == null || p === k ? 'var(--volt)' : '#8aa62a') : p == null ? 'var(--load)' : p === k ? '#ddd6fe' : '#6d5bb0'}
                 barLabels={weeks.map((x, k) => k === n - 1 ? 'Now' : (n - 1 - k) % 2 === 0 ? dayLabel(x.week) : '')}
                 label="Load per week, last 8 weeks" picked={picked} onPick={setPicked} />
    </Card>
  )
}

export function Trends() {
  const { ambient } = usePhone()
  const a = ambient!
  return (
    <div className="ph-stack">
      <h1 className="ph-title">Trends</h1>
      <TrendsNav on="load" />
      <LoadCard a={a} />
      {a.sweet_spot && <WeeksCard a={a} />}

      <section className="ph-section">
        <span className="ph-label" style={{ padding: '0 4px' }}>Am I improving?</span>
        {MAIN_SPORTS.map(sp => {
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
                  <TrendPill trend={c.trend} stale={c.stale} />
                </div>
              )}
            </>
          )
          const style = { borderTopColor: SPORT_COLOR[sp] }
          return t
            ? <Link key={sp} to={`/trends/sport/${sp}`} className="ph-card ph-sport-row" style={style}
                    aria-label={`${SPORT_LABEL[sp]} — all sessions`}>{inner}<ChevronRight size={18} color="var(--faint)" aria-hidden /></Link>
            : <div key={sp} className="ph-card ph-sport-row" style={style}>{inner}</div>
        })}
        <Link to="/trends/sport/all" className="ph-card ph-last">
          <Activity size={24} color="var(--volt)" aria-hidden />
          <div className="ph-grow"><span className="ph-strong">All activities</span><span className="ph-foot">Every session, hikes and yoga included</span></div>
          <ChevronRight size={18} color="var(--faint)" aria-hidden />
        </Link>
      </section>
    </div>
  )
}
