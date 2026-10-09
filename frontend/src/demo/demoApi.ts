import type { BuddySettings, Session, VerdictKind, WallState } from '../api'
import { DEMO_LOCKED } from './demo'

/** The demo's stand-in for the server: GETs read the JSON that `fitvio demo-export` wrote to demo-data/,
 *  harmless taps (pick a person, dismiss a verdict, buddy, auto-sync switch) change an in-memory copy until
 *  a reload, and everything that would log in, sync or change settings is refused. */

type ListRow = Session & { verdict: VerdictKind | null; headline: string | null }

/** Same mapping as backend/fitvio/demo_export.py `file_for`: /api/users/alex/pmc?days=90 → users/alex/pmc-90.json */
export function fileFor(path: string): string {
  const [route, query = ''] = decodeURIComponent(path).replace(/^\/api\//, '').split('?')
  const days = new URLSearchParams(query).get('days')
  return `${route.replace(/[^A-Za-z0-9./-]/g, '_')}${days ? `-${days}` : ''}.json`
}

const files = new Map<string, Promise<unknown>>()
function load<T>(file: string): Promise<T> {
  if (!files.has(file)) {
    files.set(file, fetch(`${import.meta.env.BASE_URL}demo-data/${file}`).then(r => {
      if (!r.ok) throw new Error(`${r.status} ${file}`)
      return r.json()
    }))
  }
  // a copy, so a screen can't change what the next one reads
  return files.get(file)!.then(v => structuredClone(v) as T)
}

const state: { selected?: string; dismissed: boolean; buddies: Record<string, string>; check?: boolean } =
  { dismissed: false, buddies: {} }

export async function demoGet<T>(path: string): Promise<T> {
  const url = new URL(path, 'http://demo')
  const parts = url.pathname.split('/').filter(Boolean)  // ['api', 'users', 'alex', 'sessions']
  if (parts[1] === 'users' && parts[3] === 'sessions') return sessions(parts[2], url.searchParams) as T
  if (parts[1] === 'users' && parts[3] === 'session-types') return sessionTypes(parts[2], url.searchParams) as T
  if (url.pathname === '/api/wall') return wall() as T
  if (url.pathname === '/api/settings/buddy') {
    const b = await load<BuddySettings>('settings/buddy.json')
    return { ...b, users: { ...b.users, ...state.buddies } } as T
  }
  if (url.pathname === '/api/settings/activity-check') {
    const c = await load<{ enabled: boolean }>('settings/activity-check.json')
    return { ...c, enabled: state.check ?? c.enabled } as T
  }
  if (parts[1] === 'jobs') throw new Error('404 job not found')
  return load<T>(fileFor(path))
}

async function sessions(user: string, q: URLSearchParams): Promise<ListRow[]> {
  const all = await load<ListRow[]>(fileFor(`/api/users/${user}/sessions`))
  const sport = q.get('sport'), type = q.get('type'), since = q.get('since')
  const offset = Number(q.get('offset') ?? 0), limit = Number(q.get('limit') ?? 60)
  return all.filter(s => (!sport || s.sport === sport) && (!type || s.session_type === type)
                        && (!since || s.start_time >= since)).slice(offset, offset + limit)
}

async function sessionTypes(user: string, q: URLSearchParams): Promise<{ type: string; count: number }[]> {
  const rows = await sessions(user, new URLSearchParams({ ...(q.get('sport') ? { sport: q.get('sport')! } : {}),
                                                          ...(q.get('since') ? { since: q.get('since')! } : {}), limit: '100000' }))
  const counts = new Map<string, number>()
  rows.forEach(s => counts.set(s.session_type, (counts.get(s.session_type) ?? 0) + 1))
  return [...counts].map(([type, count]) => ({ type, count })).sort((a, b) => b.count - a.count)
}

async function wall(): Promise<WallState> {
  const w = await load<WallState>('wall.json')
  const user = state.selected ?? w.user_id
  // the exported wall opens on a fresh verdict; after "Overview" (or picking someone) it shows that person's day
  if (w.mode === 'verdict' && !state.dismissed && !state.selected) return w
  if (w.mode !== 'setup' && user) return { mode: 'ambient', user_id: user, ambient: await load(`users/${user}/ambient.json`) }
  return w
}

export async function demoSend<T>(path: string, body: unknown): Promise<T> {
  const b = (body ?? {}) as Record<string, unknown>
  // the period someone looks at: harmless, kept in the page like the other taps
  if (/^\/api\/users\/[^/]+\/trend-period$/.test(path)) return { days: Number(b.days) } as T
  switch (path) {
    case '/api/wall/select': state.selected = String(b.user_id); return { ok: true } as T
    case '/api/wall/dismiss': state.dismissed = true; return { ok: true } as T
    case '/api/wall/morning': return { started: [], pending: false } as T
    case '/api/settings/buddy': state.buddies[String(b.user_id)] = String(b.animal); return demoGet<T>(path)
    case '/api/settings/activity-check': state.check = Boolean(b.enabled); return demoGet<T>(path)
    default: throw new Error(DEMO_LOCKED)
  }
}
