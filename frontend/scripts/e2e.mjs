// End-to-end test through the real backend, database and UI (made-up data only): node scripts/e2e.mjs
// Needs the normal app build in dist/ (npm run build), the backend installed (`fitvio` on PATH, or FITVIO_BIN)
// and playwright (CI: npm i --no-save playwright && npx playwright install --with-deps chromium).
// Covers leaving a session out of comparisons (#19) on the wall and the phone: confirm, recalculated
// verdicts, persistence, restore, a refused change. And the weather (#18): the session's conditions with
// their source, and the per-person Open-Meteo switch; the learned heat response (#18 part 2) on runs and
// rides and its switch. The demo's lock is checked in demo-check.mjs.
import { spawn, spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const FITVIO = process.env.FITVIO_BIN ?? 'fitvio'
const results = []
const pageErrors = []
function check(name, ok, detail = '') {
  results.push(ok)
  console.log(`${ok ? '✓' : '✗'} ${name}${ok ? '' : `  ← ${detail}`}`)
}

// --- a throwaway server with made-up people (never the real config or database) --------------------
const tmp = mkdtempSync(join(tmpdir(), 'fitvio-e2e-'))
const env = { ...process.env, FITVIO_CONFIG: join(tmp, 'users.json'), FITVIO_DB: join(tmp, 'app.db') }
writeFileSync(env.FITVIO_CONFIG, JSON.stringify({
  users: [{ id: 'alex', name: 'Alex', max_hr: 190, rest_hr: 48 }, { id: 'sam', name: 'Sam', max_hr: 185, rest_hr: 55 }],
  // same at any hour: no night screen (start = end) and no return to the overview during the test
  wall: { night_start: '00:00', night_end: '00:00', idle_return_seconds: 3600 },
}))
if (spawnSync(FITVIO, ['demo', '--days', '150'], { env, stdio: 'inherit' }).status !== 0) throw new Error('fitvio demo failed')
const port = await new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)) }) })
const server = spawn(FITVIO, ['serve', '--host', '127.0.0.1', '--port', String(port)], { env, stdio: 'ignore' })
const ROOT = `http://127.0.0.1:${port}/`
for (let i = 0; ; i++) {
  try { if ((await fetch(`${ROOT}api/health`)).ok) break } catch { /* not up yet */ }
  if (i > 60) throw new Error('the backend did not start')
  await new Promise(r => setTimeout(r, 250))
}

const api = async (path, init) => (await fetch(ROOT + path.replace(/^\//, ''), init)).json()
const detail = id => api(`/api/sessions/${encodeURIComponent(id)}`)
const { chromium } = await import('playwright')
const browser = await chromium.launch()
async function newPage(phone) {
  const ctx = await browser.newContext(phone
    ? { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }
    : { viewport: { width: 1280, height: 800 } })
  if (phone) await ctx.addInitScript(() => localStorage.setItem('fitvio.me', 'alex'))
  const p = await ctx.newPage()
  const tag = phone ? 'phone' : 'wall'
  p.on('pageerror', e => pageErrors.push(`${tag}: ${e.message}`))
  // the refused change below is a deliberate 403
  p.on('console', m => m.type() === 'error' && !m.text().includes('403') && pageErrors.push(`${tag}: ${m.text()}`))
  return p
}

try {
  // the newest run with a real baseline, and one of the sessions it was compared with
  let T
  for (const r of await api('/api/users/alex/sessions?sport=running&limit=15')) {
    const d = await detail(r.id)
    if (d.baseline_sessions.length >= 4 && d.verdict?.deltas.length) { T = d; break }
  }
  if (!T) throw new Error('no run with a baseline in the made-up data')
  const bad = T.baseline_sessions[1]
  const before = T.verdict
  const badBefore = (await detail(bad.id)).verdict
  for (let i = 0; i < 3; i++) {  // what the wall's dismiss does, so the session pages are reachable
    const w = await api('/api/wall')
    const sid = w.session?.session_id ?? w.session?.id
    if (!sid) break
    await fetch(`${ROOT}api/wall/dismiss`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                           body: JSON.stringify({ session_id: sid }) })
  }

  console.log('— wall')
  let p = await newPage(false)
  await p.goto(`${ROOT}session/${encodeURIComponent(T.id)}`)
  await p.getByText('Baseline: the sessions you were compared with').waitFor()
  const rowBtn = () => p.getByRole('button', { name: 'Leave this session out of comparisons' })
  const confirmBox = p.getByRole('group', { name: 'Leave out of comparisons' })
  check('every "Compared with" row has an exclude button', await rowBtn().count() === T.baseline_sessions.length)
  await rowBtn().nth(1).click()
  check('excluding asks for confirmation first', await confirmBox.isVisible())
  await p.getByRole('button', { name: 'Cancel' }).click()
  check('Cancel closes the confirm and changes nothing', !(await confirmBox.isVisible())
    && JSON.stringify((await detail(T.id)).verdict.baseline_ids) === JSON.stringify(before.baseline_ids))

  const badRow = (await p.locator('tbody tr').filter({ has: rowBtn() }).nth(1).locator('td').first().innerText()).trim()
  await rowBtn().nth(1).click()
  await p.getByRole('button', { name: 'Leave out', exact: true }).click()
  await confirmBox.waitFor({ state: 'detached' })
  check('the row leaves the list on screen right away', !(await p.locator('table').last().innerText()).includes(badRow), badRow)
  check('the later verdict is recalculated without it', !(await detail(T.id)).verdict.baseline_ids.includes(bad.id))
  check('its own verdict becomes "excluded"', (await detail(bad.id)).verdict.verdict === 'excluded')
  await p.reload()
  await p.getByText('Baseline: the sessions you were compared with').waitFor()
  check('still left out after a reload', !(await p.locator('table').last().innerText()).includes(badRow))

  await p.goto(`${ROOT}session/${encodeURIComponent(bad.id)}`)
  await p.getByText('Use for comparisons').waitFor()
  const hero = await p.locator('section.hero').innerText()
  check('the excluded session says so, without confidence or "You improved"',
    /excluded/i.test(hero) && /not used for comparisons/i.test(hero) && !/confidence/i.test(hero)
    && !(await p.getByText(/You improved/i).count()), hero)
  const sw = () => p.getByRole('switch', { name: 'Use for comparisons' })
  check('its switch is off', await sw().getAttribute('aria-checked') === 'false')
  await p.goto(`${ROOT}u/alex/sport/running`)
  // wait for the rows, not just the table: it renders before the sessions have loaded
  const listed = await p.locator('table').last().getByText(/excluded/i).first().waitFor({ timeout: 10000 })
    .then(() => true, () => false)
  check('the sport page lists it as Excluded', listed)

  await p.goto(`${ROOT}session/${encodeURIComponent(bad.id)}`)
  await p.getByText('Use for comparisons').waitFor()
  await sw().click()  // restoring needs no confirm
  await p.getByText('Part of your verdicts').waitFor()
  let now = (await detail(T.id)).verdict
  check('restoring brings back exactly the earlier verdicts', now.score === before.score
    && JSON.stringify(now.baseline_ids) === JSON.stringify(before.baseline_ids)
    && (await detail(bad.id)).verdict.verdict === badBefore.verdict)

  await p.route('**/baseline', r => r.fulfill({ status: 403, contentType: 'application/json',
    body: JSON.stringify({ detail: 'changes are only allowed from your home network' }) }))
  await sw().click()
  await p.getByRole('button', { name: 'Leave out', exact: true }).click()
  await p.getByRole('alert').waitFor()
  check('a refused change shows why and changes nothing', (await p.getByRole('alert').innerText()).includes('home network')
    && (await detail(bad.id)).verdict.verdict !== 'excluded' && await sw().getAttribute('aria-checked') === 'true')
  await p.close()

  console.log('— phone')
  p = await newPage(true)
  await p.goto(`${ROOT}session/${encodeURIComponent(T.id)}`)
  await p.getByText('Compared with').waitFor()
  await sw().click()
  await p.getByRole('button', { name: 'Cancel' }).click()
  check('Cancel keeps the switch on', await sw().getAttribute('aria-checked') === 'true')
  await sw().click()
  const leave = p.getByRole('button', { name: 'Leave out', exact: true })
  await p.waitForTimeout(600)  // the confirm scrolls into view
  const box = await leave.boundingBox()
  check('the confirm is on screen above the tab bar, with 44 px buttons',
    !!box && box.y + box.height <= 844 - 49 && box.height >= 44, JSON.stringify(box))
  await leave.click()
  await p.getByText('Left out of verdicts').waitFor()
  check('the run is excluded and stays so after a reload', (await detail(T.id)).verdict.verdict === 'excluded'
    && await p.reload().then(() => p.getByText('Left out of verdicts').waitFor()).then(() => true))
  await p.goto(`${ROOT}verdict/${encodeURIComponent(T.id)}`)
  await p.getByText(/not used for comparisons/i).waitFor()
  const body = await p.locator('body').innerText()
  check('the verdict screen shows Excluded without an improved card or confidence',
    !/improved/i.test(body) && !/confidence/i.test(body))
  await p.goto(`${ROOT}trends/sport/running`)
  await p.getByText(/excluded/i).first().waitFor()
  check('the history shows the Excluded badge', true)
  check('the wall\'s sport trend skips it', (await api('/api/users/alex/ambient')).trends.running.last_session !== T.id)
  await p.goto(`${ROOT}session/${encodeURIComponent(T.id)}`)
  await p.getByText('Left out of verdicts').waitFor()
  await sw().click()
  await p.getByText('Part of your verdicts').waitFor()
  now = (await detail(T.id)).verdict
  check('restoring gives back the original verdict', now.verdict === before.verdict && now.score === before.score)
  const all = await api('/api/users/alex/sessions?sport=running&limit=200')
  check('nothing is left excluded', all.every(r => !r.excluded && r.verdict !== 'excluded'))
  await p.close()

  // --- weather (#18): the session's hourly weather and the per-person Open-Meteo switch ------------------
  console.log('— weather')
  const w = (await detail(T.id)).features.weather
  const conditions = async page => {
    const group = page.locator('.fact-group, .ph-dl').filter({ hasText: 'Conditions' })
    await group.waitFor()
    return group.innerText()
  }
  p = await newPage(false)
  await p.goto(`${ROOT}session/${encodeURIComponent(T.id)}`)
  let text = await conditions(p)
  check('the wall shows dew point, humidity and wind over the session',
    /Dew point/.test(text) && /Humidity/.test(text) && /Wind/.test(text) && text.includes(`${Math.round(w.dew_point_c)} °C`), text)
  check('… and where the weather came from', /Weather from\s+Open-Meteo/.test(text), text)
  await p.close()

  const rides = await Promise.all((await api('/api/users/alex/sessions?sport=cycling&limit=10')).map(r => detail(r.id)))
  const outside = rides.find(r => !r.indoor), trainer = rides.find(r => r.indoor)
  p = await newPage(false)
  await p.goto(`${ROOT}session/${encodeURIComponent(outside.id)}`)
  text = await conditions(p)
  check('an outdoor ride shows its weather too', /Dew point/.test(text) && /Weather from\s+Open-Meteo/.test(text), text)
  await p.goto(`${ROOT}session/${encodeURIComponent(trainer.id)}`)
  await p.getByText('The numbers').first().waitFor()
  check('an indoor ride has no weather', !(await p.getByText('Weather from').count()))
  await p.close()

  p = await newPage(true)
  await p.goto(`${ROOT}session/${encodeURIComponent(T.id)}`)
  text = await conditions(p)
  check('the phone shows the same conditions and source', /Dew point/.test(text) && /Weather from\s+Open-Meteo/.test(text), text)

  await p.goto(`${ROOT}me`)
  const wx = () => p.getByRole('switch', { name: 'Hourly weather from Open-Meteo' })
  await wx().waitFor()
  check('Open-Meteo is on by default', await wx().getAttribute('aria-checked') === 'true'
    && (await api('/api/users/alex/weather')).open_meteo === true)
  await wx().click()
  await p.getByText(/Uses only the weather from/).waitFor()
  check('switching it off is saved', await wx().getAttribute('aria-checked') === 'false'
    && (await api('/api/users/alex/weather')).open_meteo === false)
  await p.reload()
  await wx().waitFor()
  check('… and still off after a reload', await wx().getAttribute('aria-checked') === 'false')
  await wx().click()
  await p.getByText(/rough route/).waitFor()
  check('switching it back on is saved', (await api('/api/users/alex/weather')).open_meteo === true)

  await p.route('**/weather', r => r.request().method() === 'PUT'
    ? r.fulfill({ status: 403, contentType: 'application/json',
                  body: JSON.stringify({ detail: 'changes are only allowed from your home network' }) })
    : r.continue())
  await wx().click()
  await p.getByText(/home network/).waitFor()
  check('a refused change shows why and the switch stays on', await wx().getAttribute('aria-checked') === 'true'
    && (await api('/api/users/alex/weather')).open_meteo === true)
  await p.close()

  // --- heat response (#18 part 2): learned per person and sport, shown with the session, switchable ---------
  console.log('— heat response')
  const runs = await Promise.all((await api('/api/users/alex/sessions?sport=running&limit=60')).map(r => detail(r.id)))
  const warm = runs.find(r => !r.indoor && r.features.heat_adj_pct > 0.5)
  p = await newPage(false)
  await p.goto(`${ROOT}session/${encodeURIComponent(warm.id)}`)
  text = await conditions(p)
  check('a warm run shows its heat adjustment', text.includes(`+${warm.features.heat_adj_pct.toFixed(1)} %`), text)
  await p.close()
  const warmRide = rides.find(r => !r.indoor && r.features.heat_adj_pct > 0)
  check('outdoor rides are heat adjusted, indoor rides are not',
    !!warmRide && warmRide.features.ef_adj > warmRide.features.ef && trainer.features.heat_adj_pct === 0
      && trainer.features.ef_adj === trainer.features.ef, JSON.stringify(warmRide?.features ?? {}))

  const learned = await api('/api/users/alex/heat')
  p = await newPage(true)
  await p.goto(`${ROOT}me`)
  const hs = () => p.getByRole('switch', { name: 'Learn my heat response' })
  await hs().waitFor()
  check('learning is on by default and says what it learned', await hs().getAttribute('aria-checked') === 'true'
    && learned.learn && learned.sports.running.learned && (await p.locator('[data-heat=running]').innerText()).startsWith('Runs:'))
  await hs().click()
  await p.getByText('Uses the standard heat adjustment for everyone.').waitFor()
  const standard = await detail(warm.id)
  check('switching it off goes back to the standard factors, verdicts redone',
    (await api('/api/users/alex/heat')).learn === false && standard.features.heat_response.k === 1
      && Math.abs(standard.features.heat_adj_pct * learned.sports.running.k - warm.features.heat_adj_pct) < 0.02,
    JSON.stringify(standard.features.heat_response))
  await p.reload()
  await hs().waitFor()
  check('… and still off after a reload', await hs().getAttribute('aria-checked') === 'false')
  await hs().click()
  await p.getByText(/from your own warm sessions/).waitFor()
  check('switching it back on brings the learned factor back',
    (await detail(warm.id)).features.heat_adj_pct === warm.features.heat_adj_pct)
  await p.route('**/heat', r => r.request().method() === 'PUT'
    ? r.fulfill({ status: 403, contentType: 'application/json',
                  body: JSON.stringify({ detail: 'changes are only allowed from your home network' }) })
    : r.continue())
  await hs().click()
  await p.getByText(/home network/).waitFor()
  check('a refused change shows why and learning stays on', await hs().getAttribute('aria-checked') === 'true'
    && (await api('/api/users/alex/heat')).learn === true)
  await p.close()
} finally {
  await browser.close()
  server.kill()
  rmSync(tmp, { recursive: true, force: true })
}

check('no page or console errors', pageErrors.length === 0, pageErrors.join(' | '))
const failed = results.filter(ok => !ok).length
console.log(`\n${results.length - failed}/${results.length} passed`)
process.exit(failed ? 1 : 0)
