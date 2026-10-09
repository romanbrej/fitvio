import { useEffect, useRef } from 'react'
import { PERIODS } from '../trendPeriod'

/** One row of period buttons; the picked one is pressed (and scrolled into view when the row scrolls).
 *  Styled by the screen (`ph-chips` on the phone, `tabs` on the wall). */
export function PeriodChips({ days, onPick, className, btnClass }: {
  days: number; onPick: (days: number) => void; className: string; btnClass: string
}) {
  const row = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = row.current?.querySelector<HTMLElement>('[aria-pressed="true"]')
    const box = row.current
    if (el && box && box.scrollWidth > box.clientWidth) {
      box.scrollTo({ left: el.offsetLeft - (box.clientWidth - el.offsetWidth) / 2 })
    }
  }, [days])
  return (
    <div ref={row} className={className} role="group" aria-label="Period">
      {PERIODS.map(p => (
        <button key={p.days} className={btnClass} aria-pressed={p.days === days} onClick={() => onPick(p.days)}>
          {p.chip}
        </button>
      ))}
    </div>
  )
}
