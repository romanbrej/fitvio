import type { CSSProperties, KeyboardEvent, ReactNode } from 'react'

/** A tappable card. A <div role="button">, not a <button>: some Android WebViews (the wall tablet's Fully Kiosk)
 *  shrink a button's contents to their own width, so spacers and grid columns inside the card don't stretch. */
export function CardButton({ className = '', style, onClick, disabled = false, label, children }: {
  className?: string; style?: CSSProperties; onClick?: () => void; disabled?: boolean; label?: string; children: ReactNode
}) {
  const active = !disabled && !!onClick
  const key = (e: KeyboardEvent) => {
    if (active && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault()
      onClick!()
    }
  }
  return (
    <div role="button" tabIndex={active ? 0 : -1} aria-disabled={active ? undefined : true} aria-label={label}
         className={`card card-btn ${className}`} style={style} onClick={active ? onClick : undefined} onKeyDown={key}>
      {children}
    </div>
  )
}
