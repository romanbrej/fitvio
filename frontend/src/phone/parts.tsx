import { ChevronLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Ambient, User } from '../api'

export function Avatar({ user, size = 'md' }: { user: Pick<User, 'initials' | 'color'>; size?: 'sm' | 'md' | 'lg' | 'xl' }) {
  return <span className={`ph-avatar ${size}`} style={{ borderColor: user.color }}>{user.initials}</span>
}

/** "‹ Today" — a sub page's way back (44 px tall). */
export function Back({ to, label }: { to: string; label: string }) {
  return <Link to={to} className="ph-back"><ChevronLeft size={22} strokeWidth={2.2} aria-hidden />{label}</Link>
}

export function Card({ children, className = '', ...rest }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLElement>) {
  return <section className={`ph-card ${className}`} {...rest}>{children}</section>
}

export function SweetBar({ a, height = 12 }: { a: Ambient; height?: number }) {
  const ss = a.sweet_spot
  if (!ss) return null
  const max = Math.max(ss.high * 1.25, ss.load)
  const pct = (v: number) => `${Math.min(100, v / max * 100)}%`
  return (
    <div className="ph-sweet" style={{ height }} aria-label={`${ss.load} of a ${ss.low} to ${ss.high} sweet spot`}>
      <i className="zone" style={{ left: pct(ss.low), width: `calc(${pct(ss.high)} - ${pct(ss.low)})` }} />
      <i className="over" style={{ left: pct(ss.high), right: 0 }} />
      <i className="fill" style={{ width: pct(ss.load) }} />
    </div>
  )
}
