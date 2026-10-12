import { Loader2, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { DEMO, DEMO_LOCKED } from '../demo/demo'
import './RemovePerson.css'

const SOURCE_LOGIN = { garmin: 'saved Garmin login', intervals: 'saved Intervals.icu API key' } as const

/** "Remove <name>" and the confirm below it (#34). Removing deletes everything Fitvio keeps about the
 *  person on this server, for good; their Garmin Connect / Intervals.icu account is not touched. */
export function RemovePerson({ person, phone, label, onRemoved }: {
  person: { id: string; name: string; source?: 'garmin' | 'intervals' | null }
  phone?: boolean
  label?: string
  onRemoved: () => void
}) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { if (asking) box.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [asking])
  const btn = phone ? 'ph-btn sm' : 'btn'

  async function remove() {
    setBusy(true)
    setError(null)
    try {
      await api.removePerson(person.id)
      onRemoved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  if (!asking) {
    return (
      <button className={`${btn} remove-person`} disabled={DEMO} title={DEMO ? DEMO_LOCKED : undefined}
              onClick={() => { setError(null); setAsking(true) }}>
        <Trash2 size={phone ? 16 : 18} aria-hidden />{label ?? `Remove ${person.name}`}
      </button>
    )
  }
  const login = person.source ? `, the ${SOURCE_LOGIN[person.source]}` : ''
  return (
    <div ref={box} className="remove-confirm" role="group" aria-label={`Remove ${person.name}`}>
      <b>Remove {person.name} from Fitvio?</b>
      <span>
        This deletes {person.name}'s activities, verdicts, health data{login} and settings from this server.
        It can't be undone.{person.source && ` ${person.source === 'garmin' ? 'Garmin Connect' : 'Intervals.icu'} itself is not touched.`}
      </span>
      <div className="remove-actions">
        <button className={`${btn} danger`} disabled={busy} onClick={remove}>
          {busy && <Loader2 size={16} className="spin" aria-hidden />}Remove
        </button>
        <button className={btn} disabled={busy} onClick={() => setAsking(false)}>Cancel</button>
      </div>
      {error && <p className="remove-error" role="alert">{error}</p>}
    </div>
  )
}
