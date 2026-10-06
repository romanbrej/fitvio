import { ChevronLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import type { Ambient, PmcDay, User } from '../api'
import { formState, num, signed } from '../format'

export function Avatar({ user, size = 'md' }: { user: Pick<User, 'initials' | 'color'>; size?: 'sm' | 'md' | 'lg' | 'xl' }) {
  return <span className={`ph-avatar ${size}`} style={{ borderColor: user.color }}>{user.initials}</span>
}

/** "‹ Today" — a sub page's way back (44 px tall). With in-app history it goes back where you came from
 *  (a list keeps its scroll spot and filter); opened directly, it goes to `to`. */
export function Back({ to, label }: { to: string; label: string }) {
  const nav = useNavigate()
  const loc = useLocation()
  const inApp = loc.key !== 'default'
  return (
    <Link to={to} className="ph-back" onClick={e => { if (inApp) { e.preventDefault(); nav(-1) } }}>
      <ChevronLeft size={22} strokeWidth={2.2} aria-hidden />{inApp ? 'Back' : label}
    </Link>
  )
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

/** Fitness, fatigue and form side by side. `legend` adds the line style each has in the chart below it. */
export function FormNumbers({ form, legend = false }: { form: PmcDay | null; legend?: boolean }) {
  const state = formState(form?.form)
  const mark = (line: string) => legend ? `${line} ` : ''
  return (
    <div className="ph-grid3">
      <div><span className="ph-foot" style={{ color: 'var(--fitness)' }}>{mark('—')}Fitness</span><b className="num ph-v">{num(form?.fitness)}</b></div>
      <div><span className="ph-foot" style={{ color: 'var(--fatigue)' }}>{mark('- -')}Fatigue</span><b className="num ph-v">{num(form?.fatigue)}</b></div>
      <div><span className="ph-foot" style={{ color: 'var(--form)' }}>{mark('—')}Form</span><b className="num ph-v" style={{ color: 'var(--form)' }}>{signed(form?.form, 0)}</b>
        <span className={`${legend ? 'ph-caption' : 'ph-foot'} tone-${state.tone}`}>{state.label.split(' — ')[0]}</span></div>
    </div>
  )
}
