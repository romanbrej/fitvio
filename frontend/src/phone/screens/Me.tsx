import { AlertTriangle, Ban, Loader2, Plus, RefreshCw, Wifi } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api'
import { DEMO, DEMO_LOCKED } from '../../demo/demo'
import type { Account, ActivityCheck, BuddySettings, HeatResponse } from '../../api'
import { ANIMALS, Buddy } from '../../components/Buddy'
import type { Animal } from '../../components/Buddy'
import { HrSettings } from '../../components/HrSettings'
import { RemovePerson } from '../../components/RemovePerson'
import { ago } from '../../format'
import { useUnits } from '../../units'
import type { Units } from '../../units'
import { usePhone } from '../ctx'
import { Avatar, Card } from '../parts'

const errorText = (e: unknown) => String(e).replace(/^Error: /, '')

const HEAT_SPORTS: [string, string][] = [['running', 'runs'], ['cycling', 'rides']]

/** "Runs: heat costs you 1.4× the standard (38 warm runs)" */
function heatLine(r: HeatResponse['sports'][string], noun: string) {
  const what = noun[0].toUpperCase() + noun.slice(1)
  if (!r.learned || Math.abs(r.k - r.prior_k) < 0.05) {
    return `${what}: standard${r.prior_k !== 1 ? ` (${r.prior_k}× the run table)` : ''}${r.learned ? ` · ${r.warm} warm ${noun}` : ''}`
  }
  return `${what}: heat costs you ${(r.k / r.prior_k).toFixed(1)}× the standard (${r.warm} warm ${noun})`
}

const UNIT_CHOICES: [Units, string, string][] = [['metric', 'Metric', 'km · °C · kg'], ['imperial', 'Imperial', 'mi · °F · lb']]

/** Who uses this phone, their heart-rate values, units, their buddy, the accounts and auto-sync. */
export function Me() {
  const { config, me, setMe, refresh, reloadConfig } = usePhone()
  const units = useUnits()
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [buddies, setBuddies] = useState<BuddySettings | null>(null)
  const [check, setCheck] = useState<ActivityCheck | null>(null)
  const [openMeteo, setOpenMeteo] = useState<boolean | null>(null)
  const [heat, setHeat] = useState<HeatResponse | null>(null)
  const [wind, setWind] = useState<boolean | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  const load = useCallback(() => api.accounts().then(setAccounts).catch(e => setProblem(errorText(e))), [])
  useEffect(() => { load() }, [load])
  useEffect(() => { api.buddySettings().then(setBuddies).catch(() => setBuddies(null)) }, [])
  useEffect(() => { api.activityCheck().then(setCheck).catch(() => setCheck(null)) }, [])
  useEffect(() => { api.weatherSetting(me.id).then(r => setOpenMeteo(r.open_meteo)).catch(() => setOpenMeteo(null)) }, [me.id])
  useEffect(() => { api.heatSetting(me.id).then(setHeat).catch(() => setHeat(null)) }, [me.id])
  useEffect(() => { api.windSetting(me.id).then(r => setWind(r.wind)).catch(() => setWind(null)) }, [me.id])
  useEffect(() => {
    // keep sync progress fresh while anything runs
    if (!accounts?.some(a => a.job)) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [accounts, load])

  const syncNow = async (id: string) => {
    setProblem(null)
    try { await api.syncNow(id); await load() } catch (e) { setProblem(errorText(e)) }
  }
  const pickBuddy = async (animal: Animal) => {
    setProblem(null)
    try { setBuddies(await api.setBuddy(me.id, { animal, enabled: true })); refresh() } catch (e) { setProblem(errorText(e)) }
  }
  const hideBuddy = async () => {
    setProblem(null)
    try { setBuddies(await api.setBuddy(me.id, { enabled: false })); refresh() } catch (e) { setProblem(errorText(e)) }
  }
  const toggleCheck = async () => {
    if (!check) return
    setProblem(null)
    try { setCheck(await api.setActivityCheck(!check.enabled)) } catch (e) { setProblem(errorText(e)) }
  }
  const toggleWeather = async () => {
    if (openMeteo == null) return
    setProblem(null)
    try { setOpenMeteo((await api.setWeatherSetting(me.id, !openMeteo)).open_meteo); await load() } catch (e) { setProblem(errorText(e)) }
  }
  const toggleHeat = async () => {
    if (!heat) return
    setProblem(null)
    try { setHeat(await api.setHeatSetting(me.id, !heat.learn)) } catch (e) { setProblem(errorText(e)) }
  }
  const toggleWind = async () => {
    if (wind == null) return
    setProblem(null)
    try {
      setWind((await api.setWindSetting(me.id, !wind)).wind)
      api.heatSetting(me.id).then(setHeat).catch(() => {})  // the heat response is relearned on what now counts
    } catch (e) { setProblem(errorText(e)) }
  }
  const pickUnits = async (u: Units) => {
    if (u === units) return
    setProblem(null)
    // only the text changes (everything is stored in metric): the screens just load again
    try { await api.setUnitsSetting(me.id, u); reloadConfig(); await refresh() } catch (e) { setProblem(errorText(e)) }
  }
  const mine = buddies?.users[me.id]
  const shown = buddies?.enabled?.[me.id] ?? true  // missing (older backend): shown, like the backend default
  const myAccount = accounts?.find(a => a.id === me.id)

  return (
    <div className="ph-stack">
      <header className="ph-row" style={{ gap: 14 }}>
        <Avatar user={me} size="lg" />
        <div className="ph-grow"><h1 className="ph-title">{me.name}</h1><span className="ph-foot">This phone shows {me.name}</span></div>
      </header>
      {problem && <Card className="tone-worse"><span><AlertTriangle size={16} aria-hidden /> {problem}</span></Card>}

      {config.users.length > 1 && (
        <Card>
          <span className="ph-label">Who uses this phone?</span>
          <div className="ph-row" role="radiogroup" aria-label="Person on this phone" style={{ gap: 12, flexWrap: 'wrap' }}>
            {config.users.map(u => (
              <button key={u.id} role="radio" aria-checked={u.id === me.id} className={`ph-who${u.id === me.id ? ' on' : ''}`}
                      onClick={() => setMe(u.id)}>
                <Avatar user={u} size="lg" /><span>{u.name}</span>
              </button>
            ))}
          </div>
          <span className="ph-caption">Remembered on this phone only. Switching here never changes the wall.</span>
        </Card>
      )}

      {myAccount && (
        <Card>
          <span className="ph-label">Heart rate</span>
          <HrSettings account={myAccount} onSaved={load} />
        </Card>
      )}

      <Card>
        <span className="ph-label">Units</span>
        <div className="ph-row" role="radiogroup" aria-label="Units" style={{ gap: 8 }}>
          {UNIT_CHOICES.map(([u, label, what]) => (
            <button key={u} role="radio" aria-checked={u === units} className="ph-chip-btn ph-units"
                    onClick={() => pickUnits(u)}>
              <b>{label}</b><span>{what}</span>
            </button>
          ))}
        </div>
        <span className="ph-caption">For {me.name} on every screen, the wall too. Stored in metric, so switching changes no verdict.</span>
      </Card>

      {openMeteo != null && (
        <Card>
          <span className="ph-label">Weather</span>
          <div className="ph-list-row">
            <div className="ph-grow">
              <span className="ph-strong">Hourly weather from Open-Meteo</span>
              <span className="ph-foot">{openMeteo
                ? 'Temperature, dew point and wind over each outdoor session, for the heat adjustment. Sends only a rough route (about 11 km).'
                : `Uses only the weather from ${myAccount?.source === 'intervals' ? 'Intervals.icu' : 'Garmin'}.`}</span>
            </div>
            <button role="switch" aria-checked={openMeteo} className={`switch ${openMeteo ? 'on' : ''}`}
                    onClick={toggleWeather} aria-label="Hourly weather from Open-Meteo"><span /></button>
          </div>
          {heat?.available && (
            <div className="ph-list-row">
              <div className="ph-grow">
                <span className="ph-strong">Learn my heat response</span>
                <span className="ph-foot">{heat.learn
                  ? 'How much heat slows you, from your own warm sessions compared with the cooler ones around them.'
                  : 'Uses the standard heat adjustment for everyone.'}</span>
                {HEAT_SPORTS.filter(([sport]) => heat.sports[sport]).map(([sport, noun]) => (
                  <span key={sport} className="ph-foot" data-heat={sport}>{heatLine(heat.sports[sport], noun)}</span>
                ))}
              </div>
              <button role="switch" aria-checked={heat.learn} className={`switch ${heat.learn ? 'on' : ''}`}
                      onClick={toggleHeat} aria-label="Learn my heat response"><span /></button>
            </div>
          )}
          {wind != null && (
            <div className="ph-list-row">
              <div className="ph-grow">
                <span className="ph-strong">Correct runs for wind</span>
                <span className="ph-foot">{wind
                  ? 'Pace into a headwind counts for more, with a tailwind for less, from your direction and the hourly wind.'
                  : 'Runs are judged as run, whatever the wind.'}</span>
              </div>
              <button role="switch" aria-checked={wind} className={`switch ${wind ? 'on' : ''}`}
                      onClick={toggleWind} aria-label="Correct runs for wind"><span /></button>
            </div>
          )}
        </Card>
      )}

      {buddies && (
        <Card>
          <div className="ph-row" style={{ gap: 12 }}>
            {mine && shown && <Buddy animal={mine} mood="happy" size={56} />}
            <div className="ph-grow"><span className="ph-label">Training buddy</span><span className="ph-strong" style={{ textTransform: 'capitalize' }}>{shown ? mine ?? '—' : 'None'}</span></div>
          </div>
          <div className="ph-buddies" role="radiogroup" aria-label="Buddy animal">
            <button role="radio" aria-checked={!shown} className={shown ? '' : 'on'} onClick={hideBuddy} aria-label="No training buddy">
              <Ban size={36} strokeWidth={1.5} aria-hidden /><span>None</span>
            </button>
            {ANIMALS.map(an => (
              <button key={an} role="radio" aria-checked={shown && mine === an} className={shown && mine === an ? 'on' : ''}
                      onClick={() => pickBuddy(an)} aria-label={`${an}, eats ${buddies.food[an]}`}>
                <Buddy animal={an} mood="happy" size={36} /><span>{an}</span>
              </button>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <span className="ph-label">Accounts</span>
        {accounts?.map(a => (
          <div key={a.id} className="ph-list-row">
            <Avatar user={a} size="sm" />
            <div className="ph-grow">
              <span className="ph-strong">{a.name}</span>
              {a.job ? <span className="ph-foot">Syncing…</span>
                : a.sync.login_expired ? <span className="ph-foot tone-warn">Garmin login expired — Sync logs in again</span>
                : a.sync.last_error ? <span className="ph-foot tone-warn">Last sync failed{a.source === 'intervals' && /API key/.test(a.sync.last_error) ? ' — check the API key' : ''}</span>
                : <span className={`ph-foot ${a.sync.stale ? 'tone-warn' : 'tone-better'}`}>Synced {ago(a.sync.last_success)}</span>}
            </div>
            <button className={`ph-btn sm${a.sync.login_expired ? ' warn' : ''}`} onClick={() => syncNow(a.id)} disabled={!!a.job || DEMO} title={DEMO ? DEMO_LOCKED : undefined}
                    aria-label={`Sync ${a.name} now`}>
              {a.job ? <Loader2 size={16} className="spin" aria-hidden /> : <RefreshCw size={16} aria-hidden />}{a.sync.login_expired ? 'Fix' : 'Sync'}
            </button>
          </div>
        ))}
        {check && (
          <div className="ph-list-row">
            <div className="ph-grow">
              <span className="ph-strong">Auto-sync on new activity</span>
              <span className="ph-foot">{check.backoff_until ? `Paused until ${check.backoff_until.slice(11, 16)} (Garmin rate limit)`
                : `Checks for new activities every ${Math.round(check.interval_s / 60)}–10 min, ${check.active_hours}`}</span>
            </div>
            <button role="switch" aria-checked={check.enabled} className={`switch ${check.enabled ? 'on' : ''}`}
                    onClick={toggleCheck} aria-label="Auto-sync on new activity"><span /></button>
          </div>
        )}
        <Link to="/me/connect" className="ph-list-row ph-add"><Plus size={22} aria-hidden />Add a person</Link>
      </Card>

      <Card>
        <span className="ph-label">Remove</span>
        <RemovePerson person={{ id: me.id, name: me.name, source: myAccount?.source }} phone label={`Remove ${me.name} from Fitvio`}
                      onRemoved={() => { setMe(null); reloadConfig() }} />
      </Card>

      <p className="ph-note"><Wifi size={18} aria-hidden />Fitvio runs on your home server and only works on your home Wi-Fi. Your logins and health data never leave your house.</p>
    </div>
  )
}
