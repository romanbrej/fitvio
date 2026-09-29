import { Star } from 'lucide-react'
import type { Improvement } from '../api'
import { formState, signed } from '../format'
import './Improvements.css'

const MARK: Record<string, string> = { improving: '▲', steady: '●', declining: '▼' }
const TONE: Record<string, string> = { improving: 'better', steady: 'inline', declining: 'worse', best: 'better' }

/** The ▲/●/▼/★ rows, shared by the card below and the wall's "Last workout" card. */
export function ImprovementList({ items, max, compact }: { items: Improvement[]; max?: number; compact?: boolean }) {
  return (
    <ul className={`improve-list${compact ? ' compact' : ''}`}>
      {items.slice(0, max).map((i, n) => (
        <li key={`${i.kind}-${n}`} className={`tone-${i.tone ? TONE[i.tone] : 'muted'}`}>
          <span className="improve-mark">{i.tone === 'best' ? <Star size={16} fill="currentColor" /> : MARK[i.tone ?? ''] ?? '·'}</span>
          <span className="improve-label">{i.label}</span>
          <span className="improve-value num">{i.value_fmt}</span>
          <span className="improve-change">{i.change_fmt}</span>
        </li>
      ))}
    </ul>
  )
}

export function improvedCount(items: Improvement[]): number {
  return items.filter(i => i.tone === 'improving' || i.tone === 'best').length
}

/** "What improved" after an activity: fitness, performance vs your usual, VO₂max, new bests. */
export function Improvements({ items, formTomorrow, onClick }: {
  items: Improvement[]; formTomorrow?: number | null; onClick?: () => void
}) {
  const up = improvedCount(items)
  const fs = formState(formTomorrow)
  return (
    <button className="card improvements" onClick={onClick} disabled={!onClick}>
      <div className="between">
        <div className="card-title" style={{ margin: 0 }}>What improved</div>
        {items.length > 0 && <span className={`improve-count tone-${up ? 'better' : 'inline'}`}>{up} of {items.length}</span>}
      </div>
      <ImprovementList items={items} />
      {formTomorrow != null && (
        <div className="improve-foot muted">Form tomorrow <b className="num" style={{ color: 'var(--form)' }}>{signed(formTomorrow, 0)}</b> · <span className={`tone-${fs.tone}`}>{fs.label}</span></div>
      )}
    </button>
  )
}
