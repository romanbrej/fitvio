import { AlertTriangle, Pencil } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import type { Account } from '../api'
import './HrSettings.css'

const FIELDS = [['max_hr', 'Max HR'], ['rest_hr', 'Resting HR']] as const
const SOURCE_NAME = { garmin: 'Garmin', intervals: 'Intervals.icu' } as const

/** Not from a watch or a setting: a guess the person should check. */
const isGuess = (source: string) => /^(estimated|default)/.test(source)

/** Max and resting HR with where they come from, and your own values when the source is wrong.
 *  Zones, load and the reference HR of the whole history follow (the server reprocesses). */
export function HrSettings({ account, onSaved }: { account: Account; onSaved: () => void }) {
  const p = account.profile
  const [editing, setEditing] = useState(false)
  const [values, setValues] = useState({ max_hr: '', rest_hr: '' })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const own = FIELDS.some(([k]) => p[k].source === 'set by you')
  const guess = FIELDS.some(([k]) => isGuess(p[k].source))

  const open = () => {
    setValues({ max_hr: String(Math.round(Number(p.max_hr.value))), rest_hr: String(Math.round(Number(p.rest_hr.value))) })
    setError(null)
    setEditing(true)
  }
  const save = async (v: { max_hr: number | null; rest_hr: number | null }) => {
    setBusy(true); setError(null)
    try {
      await api.setProfile(account.id, v)
      setEditing(false)
      onSaved()
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''))
    } finally {
      setBusy(false)
    }
  }
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    save({ max_hr: Number(values.max_hr), rest_hr: Number(values.rest_hr) })
  }

  if (editing) {
    return (
      <form className="hr-settings" onSubmit={submit}>
        <div className="hr-fields">
          {FIELDS.map(([k, label]) => (
            <label key={k}>
              <span>{label}</span>
              <input inputMode="numeric" pattern="[0-9]*" maxLength={3} required value={values[k]}
                     onChange={e => setValues({ ...values, [k]: e.target.value.replace(/\D/g, '') })} />
            </label>
          ))}
        </div>
        {error && <div className="hr-error" role="alert"><AlertTriangle size={16} aria-hidden /> {error}</div>}
        <div className="hr-actions">
          <button className="btn primary" type="submit" disabled={busy}>Save</button>
          <button className="btn" type="button" onClick={() => setEditing(false)} disabled={busy}>Cancel</button>
          {own && account.source && (
            <button className="btn" type="button" disabled={busy} onClick={() => save({ max_hr: null, rest_hr: null })}>
              Use {SOURCE_NAME[account.source]}'s values
            </button>
          )}
        </div>
        <span className="hr-note">Heart-rate zones, training load and the pace at your reference HR are recalculated for your whole history.</span>
      </form>
    )
  }

  return (
    <div className="hr-settings">
      <div className="hr-values">
        {FIELDS.map(([k, label]) => (
          <div key={k}>
            <span className="hr-label">{label}</span>
            <b className="num">{p[k].value == null ? '—' : Math.round(Number(p[k].value))}</b>
            <span className={`hr-source${isGuess(p[k].source) ? ' guess' : ''}`}>{p[k].source}</span>
          </div>
        ))}
        <button className="btn hr-edit" onClick={open} aria-label={`Change max and resting HR for ${account.name}`}>
          <Pencil size={16} aria-hidden /> Change
        </button>
      </div>
      {guess && (
        <span className="hr-note warn"><AlertTriangle size={15} aria-hidden /> Estimated — if you know your real values, enter them: every
          zone and the pace at your reference HR depend on them.</span>
      )}
    </div>
  )
}
