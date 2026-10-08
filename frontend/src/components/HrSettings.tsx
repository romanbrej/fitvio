import { AlertTriangle, Pencil, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import type { Account } from '../api'
import './HrSettings.css'

const FIELDS = [['max_hr', 'Max HR'], ['rest_hr', 'Resting HR']] as const
type Field = typeof FIELDS[number][0]
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
  const isOwn = (k: Field) => p[k].source === 'set by you'
  const own = FIELDS.some(([k]) => isOwn(k))
  const suggested = p.max_hr.suggested
  const shown = (k: Field) => String(Math.round(Number(p[k].value)))
  const guess = FIELDS.some(([k]) => isGuess(p[k].source))

  const open = () => {
    setValues({ max_hr: shown('max_hr'), rest_hr: shown('rest_hr') })
    setError(null)
    setEditing(true)
  }
  const run = async (call: () => Promise<unknown>) => {
    setBusy(true); setError(null)
    try {
      await call()
      setEditing(false)
      onSaved()
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''))
    } finally {
      setBusy(false)
    }
  }
  const save = (v: { max_hr: number | null; rest_hr: number | null }) => run(() => api.setProfile(account.id, v))
  /** A field becomes your own only when you changed it (or it already was): the other keeps following the sync. */
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const pick = (k: Field) => isOwn(k) || values[k] !== shown(k) ? Number(values[k]) : null
    save({ max_hr: pick('max_hr'), rest_hr: pick('rest_hr') })
  }
  const keepOwnRest = isOwn('rest_hr') ? Number(p.rest_hr.value) : null

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
      {suggested && (
        <div className="hr-suggest" role="status">
          <span className="hr-note"><RefreshCw size={15} aria-hidden />
            <span>{account.source ? SOURCE_NAME[account.source] : 'Your data'} now says <b className="num">{Math.round(suggested.value)}</b> for
              max HR ({suggested.source}). Your {shown('max_hr')} counts until you take it.</span></span>
          <div className="hr-actions">
            <button className="btn primary" disabled={busy} onClick={() => save({ max_hr: null, rest_hr: keepOwnRest })}>
              Use {Math.round(suggested.value)}
            </button>
            <button className="btn" disabled={busy} onClick={() => run(() => api.dismissProfile(account.id, 'max_hr'))}>
              Keep mine
            </button>
          </div>
          {error && <div className="hr-error" role="alert"><AlertTriangle size={16} aria-hidden /> {error}</div>}
        </div>
      )}
      {guess && (
        <span className="hr-note warn"><AlertTriangle size={15} aria-hidden /> Estimated — if you know your real values, enter them: every
          zone and the pace at your reference HR depend on them.</span>
      )}
    </div>
  )
}
