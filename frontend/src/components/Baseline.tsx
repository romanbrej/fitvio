import { Ban, Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { SessionDetail } from '../api'
import './Baseline.css'

/** Leaving a badly recorded session out of comparisons (dead watch, broken HR strap): the session's own
 *  switch, an exclude button on each "Compared with" row, and the confirm in between. Excluding asks
 *  first because it recalculates the verdicts of later sessions; bringing a session back doesn't. */

export interface Baseline {
  session: SessionDetail
  confirm: string | null  // the session waiting for "Leave out"
  busy: boolean
  error: string | null
  ask: (id: string) => void
  cancel: () => void
  apply: (id: string, excluded: boolean) => Promise<void>
}

/** `session` as loaded; after a change it's the session as the server recalculated it. */
export function useBaseline(session: SessionDetail): Baseline {
  const [updated, setUpdated] = useState<SessionDetail | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const current = updated?.id === session.id ? updated : session

  async function apply(id: string, excluded: boolean) {
    setBusy(true)
    setError(null)
    try {
      const changed = await api.setBaseline(id, excluded)
      setUpdated(id === current.id ? changed : await api.session(current.id))
      setConfirm(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return {
    session: current, confirm, busy, error, apply,
    ask: id => { setError(null); setConfirm(id) },
    cancel: () => { setError(null); setConfirm(null) },
  }
}

/** "Use for comparisons" with its switch; off asks for confirmation, on restores right away. */
export function BaselineSwitch({ b, phone }: { b: Baseline; phone?: boolean }) {
  const s = b.session
  const used = !s.excluded_from_baseline
  return (
    <div className="baseline">
      <div className="baseline-row">
        <div className="baseline-text">
          <span className="baseline-title">Use for comparisons</span>
          <span className="baseline-foot">
            {used ? 'Part of your verdicts, trends and bests. Turn it off if the watch recorded this session badly.'
              : 'Left out of verdicts, trends and bests. It still counts for training load.'}
          </span>
        </div>
        <button role="switch" aria-checked={used} className={`switch ${used ? 'on' : ''}`} disabled={b.busy}
                onClick={() => used ? b.ask(s.id) : b.apply(s.id, false)} aria-label="Use for comparisons"><span /></button>
      </div>
      {b.confirm === s.id && <ConfirmExclude b={b} id={s.id} what="this session" phone={phone} />}
      {b.error && b.confirm === null && <p className="baseline-error" role="alert">{b.error}</p>}
    </div>
  )
}

/** "Leave … out of comparisons? Later verdicts are recalculated." with Leave out / Cancel. */
export function ConfirmExclude({ b, id, what, phone }: { b: Baseline; id: string; what: string; phone?: boolean }) {
  const btn = phone ? 'ph-btn sm' : 'btn'
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { box.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [id])  // below the fold on a phone
  return (
    <div ref={box} className="baseline-confirm" role="group" aria-label="Leave out of comparisons">
      <span>Leave {what} out of comparisons? Later verdicts are recalculated.</span>
      <div className="baseline-actions">
        <button className={`${btn} primary`} disabled={b.busy} onClick={() => b.apply(id, true)}>
          {b.busy && <Loader2 size={16} className="spin" aria-hidden />}Leave out
        </button>
        <button className={btn} disabled={b.busy} onClick={b.cancel}>Cancel</button>
      </div>
      {b.error && <p className="baseline-error" role="alert">{b.error}</p>}
    </div>
  )
}

/** The small exclude button on a "Compared with" row (44 pt target). */
export function ExcludeButton({ b, id }: { b: Baseline; id: string }) {
  return (
    <button className="baseline-exclude" aria-label="Leave this session out of comparisons" disabled={b.busy}
            onClick={e => { e.stopPropagation(); b.ask(id) }}>
      <Ban size={18} aria-hidden />
    </button>
  )
}
