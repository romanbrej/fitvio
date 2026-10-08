// Checks the built demo before it is published: node scripts/demo-check.mjs <dist dir>
//  1. coverage: every GET in src/api.ts has exported demo data (or is answered in src/demo/demoApi.ts)
//  2. smoke test: a headless browser opens the demo page and every wall and phone screen for both people, and
//     fails on page errors, failed requests or a screen still saying "Loading…".
// Needs playwright (CI: npm i --no-save playwright && npx playwright install --with-deps chromium).
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, resolve } from 'node:path'

const dist = resolve(process.argv[2] ?? 'dist')
const data = join(dist, 'demo-data')
const problems = []

// --- 1. coverage ------------------------------------------------------------
// answered in the browser from other files (demoApi.ts), not exported one-to-one
const COMPUTED = new Set(['users/*/sessions', 'users/*/session-types', 'wall', 'settings/buddy', 'settings/activity-check', 'jobs/*'])
const api = readFileSync(new URL('../src/api.ts', import.meta.url), 'utf8')
// `/api/users/${seg(user)}/pmc?days=${days}` → users/*/pmc: every ${…} (braces may nest) becomes *, query dropped
function route(template) {
  let out = '', depth = 0
  for (let i = 0; i < template.length; i++) {
    if (depth === 0 && template.startsWith('${', i)) { depth = 1; out += '*'; i++; continue }
    if (depth > 0) { depth += template[i] === '{' ? 1 : template[i] === '}' ? -1 : 0; continue }
    out += template[i]
  }
  return out.split('?')[0].replace(/^\/api\//, '').replace(/([^/])\*$/, '$1')
}
const routes = [...api.matchAll(/get<[^(]*>\(\s*([`'])(\/api\/.*?)\1\)/g)].map(m => route(m[2]))
const files = []
const walk = dir => readdirSync(dir).forEach(f => statSync(join(dir, f)).isDirectory() ? walk(join(dir, f)) : files.push(join(dir, f).slice(data.length + 1)))
walk(data)
for (const route of new Set(routes)) {
  if (COMPUTED.has(route)) continue
  const re = new RegExp(`^${route.replace(/\*/g, '[^/]+')}(-\\d+)?\\.json$`)
  if (!files.some(f => re.test(f))) problems.push(`no demo data for GET /api/${route}`)
}
for (const f of ['config.json', 'wall.json', 'settings/buddy.json', 'settings/activity-check.json']) {
  if (!existsSync(join(data, f))) problems.push(`missing demo-data/${f}`)
}
if (problems.length) finish()

// --- 2. smoke test ----------------------------------------------------------
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.woff': 'font/woff', '.png': 'image/png' }
const BASE = '/fitvio/'  // as on GitHub Pages: the site lives under the repo name
const server = createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, 'http://x').pathname)
  let f = path.startsWith(BASE) ? join(dist, path.slice(BASE.length)) : null
  if (f && existsSync(f) && statSync(f).isDirectory()) f = join(f, 'index.html')
  if (!f || !f.startsWith(dist) || !existsSync(f)) { res.writeHead(404).end(); return }
  res.writeHead(200, { 'Content-Type': TYPES[extname(f)] ?? 'application/octet-stream' }).end(readFileSync(f))
})
await new Promise(r => server.listen(0, '127.0.0.1', r))
const root = `http://127.0.0.1:${server.address().port}${BASE}`

const { chromium } = await import('playwright')
const browser = await chromium.launch()
const users = JSON.parse(readFileSync(join(data, 'config.json'), 'utf8')).users.map(u => u.id)
const firstSession = u => JSON.parse(readFileSync(join(data, 'users', u, 'sessions.json'), 'utf8'))[0]?.id

async function check(label, url, viewport, { phoneUser, expect } = {}) {
  const ctx = await browser.newContext({ viewport, isMobile: viewport.width < 700, hasTouch: viewport.width < 700 })
  if (phoneUser) await ctx.addInitScript(id => localStorage.setItem('fitvio.me', id), phoneUser)
  const page = await ctx.newPage()
  const errors = []
  page.on('pageerror', e => errors.push(`page error: ${e.message}`))
  page.on('console', m => m.type() === 'error' && errors.push(`console: ${m.text()}`))
  page.on('requestfailed', r => errors.push(`request failed: ${r.url()}`))
  page.on('response', r => r.status() >= 400 && errors.push(`${r.status()} ${r.url()}`))
  await page.goto(url)
  try {
    await page.waitForFunction(() => !document.body.innerText.includes('Loading…') && document.body.innerText.trim().length > 0,
      null, { timeout: 5000 })
  } catch { errors.push('still "Loading…" after 5 s') }
  await page.waitForTimeout(300)
  if (expect && !(await page.locator('body').innerText()).includes(expect)) errors.push(`"${expect}" not shown`)
  errors.forEach(e => problems.push(`${label}: ${e}`))
  console.log(`${errors.length ? '✗' : '✓'} ${label}`)
  await ctx.close()
}

const desktop = { width: 1440, height: 900 }
const wall = { width: 1280, height: 800 }
const phone = { width: 390, height: 844 }
await check('landing', root, desktop, { expect: 'Wall display' })
await check('landing (phone)', root, phone, { expect: 'Phone app' })
for (const u of users) {
  const sid = encodeURIComponent(firstSession(u))
  for (const r of ['', 'accounts', `session/${sid}`, `u/${u}/load`, `u/${u}/health/hrv`, `u/${u}/sport/running`,
                   `u/${u}/validation`, `u/${u}/plan`]) {
    await check(`wall /${r} (${u})`, `${root}?app#/${r}`, wall)
  }
  for (const r of ['', 'plan', 'trends', 'trends/health', 'trends/sport/running', 'me', 'me/connect', `session/${sid}`, `verdict/${sid}`]) {
    await check(`phone /${r} (${u})`, `${root}?app#/${r}`, phone, { phoneUser: u })
  }
}
// changes the demo can't make are refused with the demo message (here: leaving a session out of comparisons)
{
  const u = users[0]
  const ctx = await browser.newContext({ viewport: phone, isMobile: true, hasTouch: true })
  await ctx.addInitScript(id => localStorage.setItem('fitvio.me', id), u)
  const page = await ctx.newPage()
  await page.goto(`${root}?app#/session/${encodeURIComponent(firstSession(u))}`)
  let ok = false
  try {
    await page.getByRole('switch', { name: 'Use for comparisons' }).click({ timeout: 5000 })
    await page.getByRole('button', { name: 'Leave out', exact: true }).click({ timeout: 5000 })
    ok = (await page.getByRole('alert').innerText({ timeout: 5000 })).includes('Not available in the demo')
  } catch { /* reported below */ }
  if (!ok) problems.push('excluding a session in the demo does not show the demo lock')
  console.log(`${ok ? '✓' : '✗'} demo lock: excluding a session`)
  await ctx.close()
}

await browser.close()
server.close()
finish()

function finish() {
  if (problems.length) {
    console.error(`\nThe demo is broken, not publishing it:\n${problems.map(p => `  - ${p}`).join('\n')}`)
    process.exit(1)
  }
  console.log('\nDemo OK')
  process.exit(0)
}
