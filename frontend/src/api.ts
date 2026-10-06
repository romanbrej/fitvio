export type Sport = 'running' | 'cycling' | 'swimming' | 'strength' | 'other'
export type VerdictKind = 'better' | 'in_line' | 'worse' | 'not_comparable' | 'load_only'

export interface User { id: string; name: string; color: string; initials: string }
export interface AppConfig {
  users: User[]
  wall: { idle_return_seconds: number; night_start: string; night_end: string; verdict_minutes: number }
}

export interface Delta {
  key: string; label: string; value: number | null; baseline: number | null; delta: number | null
  delta_pct: number | null; z: number | null; weight: number; better: number; n: number
  value_fmt: string; baseline_fmt: string; delta_fmt?: string; sets?: number; volume?: number
}

export interface Trend {
  fitness_before: number; fitness_after: number; fatigue_before: number; fatigue_after: number
  form_before: number; form_after: number; ramp_7d: number | null; load: number
  trend_metric?: string; trend_pct_per_week?: number | null; trend_points?: { day: string; value: number }[]
}

export interface Verdict {
  session_id: string; user_id: string; verdict: VerdictKind; confidence: 'high' | 'medium' | 'low'
  score: number | null; headline: string; reasons: string[]; deltas: Delta[]
  context: { kind: string; text: string }[]; trend: Trend; baseline_ids: string[]
}

export interface Session {
  id: string; user_id: string; name: string | null; sport: Sport; sub_sport: string | null
  session_type: string; start_time: string; duration_s: number | null; distance_m: number | null
  avg_hr: number | null; max_hr: number | null; ascent_m: number | null; avg_temp_c: number | null
  indoor: number; has_power: number; load: number | null; rpe: number | null; feel: number | null
  features: Record<string, any>; verdict: Verdict | null
  improvements?: Improvement[]
}

/** One line of "What improved" after an activity (backend: improvements.py). */
export interface Improvement {
  kind: string; label: string; value_fmt: string; change_fmt: string
  tone: 'improving' | 'steady' | 'declining' | 'best' | null
}

export interface Streams {
  t: number[]; hr: (number | null)[] | null; speed: (number | null)[] | null
  power: (number | null)[] | null; altitude: (number | null)[] | null
  laps: { start_s: number; duration_s: number; distance_m: number | null; avg_hr: number | null; avg_speed: number | null; avg_power: number | null }[]
}

export interface SessionDetail extends Session {
  streams: Streams | null
  sets: { set_index: number; exercise: string; reps: number | null; weight_kg: number | null }[]
  baseline_sessions: Pick<Session, 'id' | 'name' | 'start_time' | 'duration_s' | 'distance_m' | 'avg_hr' | 'session_type' | 'features' | 'rpe' | 'feel'>[]
}

export interface PmcDay { day: string; load: number; fitness: number; fatigue: number; form: number }

export interface HealthDay {
  day: string; rhr: number | null; hrv_last_night: number | null; hrv_weekly: number | null
  hrv_baseline_low: number | null; hrv_baseline_high: number | null; hrv_status: string | null
  sleep_total_min: number | null; sleep_deep_min: number | null; sleep_light_min: number | null
  sleep_rem_min: number | null; sleep_awake_min: number | null; sleep_score: number | null
  stress_avg: number | null; bb_max: number | null; bb_min: number | null; steps: number | null
  weight_kg: number | null; vo2max: number | null; vo2max_cycling: number | null
}

export interface SportTrend {
  last_session: string; last_time: string; last_verdict: VerdictKind; metric: string | null
  pct_per_week: number | null; points: { day: string; value: number }[]
  /** running/cycling headline in real units, computed live */
  status?: {
    pace_s_per_km?: number; change_s_per_km?: number | null
    w_per_beat?: number | null; w_per_beat_change_pct?: number | null; ftp_wkg?: number | null; hr_wkg?: number | null
    ref_hr?: number | null; points: { day: string; value: number }[]
  } | null
  /** running only: median cadence of easy/long runs in 6 weeks vs the 6 before */
  cadence?: { spm: number; change: number | null; runs: number } | null
}

/** Garmin's Training Readiness (the watch's score). */
export interface Readiness {
  day: string; score: number; level: string | null; feedback: string | null; time: string | null
  recovery_min: number | null; factors: Record<string, number | null>
}

export interface WorkoutStep {
  kind: string; duration_s: number | null; distance_m: number | null; description?: string | null
  target: { type: 'pace'; low_s_per_km: number; high_s_per_km: number }
    | { type: 'hr' | 'power' | 'cadence'; low: number; high: number } | { type: 'hr_zone'; zone: number } | null
}

export interface PlanInfo { name: string; weeks: number | null; week: number | null; end: string | null }

export type PlanStatus = 'done' | 'missed' | 'today' | 'planned' | 'rest'

/** One day of the plan strip: the planned workout (none on a rest day) and what became of it. */
export interface PlanDay {
  day: string; status: PlanStatus
  title?: string; sport?: Sport; phrase?: string | null; description?: string | null
  est_duration_s?: number | null; est_load?: number | null; steps?: WorkoutStep[]
  session_id?: string; verdict?: VerdictKind | null; targets?: { hit: number; of: number } | null
  done?: PlannedWorkout['done']
}

/** Seven days of the Garmin plan (Mon–Sun; on a Sunday from today on). */
export interface PlanWeek {
  start: string; days: PlanDay[]; done: number; due: number; planned: number; plan: PlanInfo | null
}

/** A planned workout from the Garmin Connect calendar (Garmin Coach or your own). */
export interface PlannedWorkout {
  day: string; title: string; sport: Sport; description: string | null; phrase: string | null
  est_duration_s: number | null; est_distance_m: number | null; est_load: number | null
  est_training_effect?: number | null; steps: WorkoutStep[]; source: string; fetched_at: string
  plan?: PlanInfo | null
  done?: {
    session_id: string; name: string | null; linked: boolean; verdict: VerdictKind | null; headline: string | null
    load: number | null; targets: { hit: number; of: number } | null
  } | null
}

export interface Streak {
  weeks: number; this_week: number; needed: number; min_sessions: number; days_left: number
  history: { week: string; count: number }[]
}

/** The training buddy (backend: buddy.py). */
export interface BuddyInfo {
  animal: 'mouse' | 'cat' | 'bunny' | 'fox' | 'bear' | 'penguin' | 'frog' | 'hedgehog'
  food: string; mood: 'happy' | 'content' | 'sleepy' | 'overjoyed' | 'hungry'; line: string
}
export interface BuddySettings { animals: BuddyInfo['animal'][]; food: Record<string, string>; users: Record<string, BuddyInfo['animal']> }

export interface SweetSpot { low: number; high: number; load: number; fitness_at_start: number }

export interface WeekTotals { [sport: string]: { count: number; duration_s: number; distance_m: number; load: number } }

export interface SyncInfo {
  last_success: string | null; last_attempt: string | null; last_error: string | null
  age_hours: number | null; stale: boolean
  login_expired?: boolean  // the auto-sync check found the cached Garmin login expired
}

/** Auto-sync on new activity (backend: sync/activity_watch.py). */
export interface ActivityCheck {
  enabled: boolean; interval_s: number; active_hours: string
  backoff_until: string | null; last_error: string | null
  users: Record<string, { last_check: string | null; login_expired: boolean }>
}

export interface Ambient {
  user_id: string; pmc: PmcDay[]; form: PmcDay | null
  /** since this morning: today's pmc row minus yesterday's */
  today_change: { fitness: number; fatigue: number; form: number } | null
  fitness_change_6w: number | null
  last_workout: {
    id: string; name: string | null; sport: Sport; session_type: string; start_time: string
    verdict: VerdictKind; headline: string; improvements: Improvement[]
  } | null
  health_latest: Partial<HealthDay>; health_baseline: Record<string, number | null>
  health_series: HealthDay[]; week: WeekTotals; last_week: WeekTotals
  trends: Partial<Record<Sport, SportTrend>>
  recent: (Pick<Session, 'id' | 'name' | 'sport' | 'session_type' | 'start_time' | 'duration_s' | 'distance_m' | 'load'> & { verdict: VerdictKind | null; headline: string | null })[]
  vo2max: { day: string; value: number }[]
  sync: SyncInfo
  readiness: Readiness | null
  streak: Streak
  sweet_spot: SweetSpot | null
  today_workout: PlannedWorkout | null
  upcoming: Pick<PlannedWorkout, 'day' | 'title' | 'sport' | 'phrase' | 'description' | 'est_duration_s' | 'est_load' | 'steps'>[]
  plan_week?: PlanWeek | null
  buddy?: BuddyInfo
}

export type WallState =
  | { mode: 'setup'; job: Job | null; user_id?: string }
  | { mode: 'ambient'; user_id: string; ambient: Ambient }
  | { mode: 'verdict'; user_id: string; session: Session; ambient: Ambient }

export interface Validation {
  days: number; rated_sessions: number; agree: number; disagree: number; agreement_pct: number | null
  flagged: { id: string; start_time: string; sport: Sport; rpe: number | null; feel: number | null; verdict: VerdictKind }[]
}

export interface Job {
  id: string; kind: 'connect' | 'sync'; user_id: string | null
  phase: 'logging_in' | 'mfa_required' | 'downloading' | 'importing' | 'done' | 'error'
  message: string; error: string | null; name: string | null; result: { activities: number } | null
  log: string[]; started_at: string; finished_at: string | null
  step: string | null; step_index: number | null; step_total: number | null
}

export interface Account {
  id: string; name: string; color: string; initials: string; sync: SyncInfo; job: Job | null
  activities: number; profile: Profile
}

export type Profile = Record<'name' | 'sex' | 'max_hr' | 'rest_hr' | 'lthr' | 'ftp' | 'weight_kg', { value: string | number | null; source: string }>

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${r.status} ${path}`)
  return r.json()
}

async function post<T = void>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok) {
    let detail = `${r.status}`
    try { detail = (await r.json()).detail ?? detail } catch { /* not JSON */ }
    throw new Error(detail)
  }
  return r.json()
}

/** A path segment from data or the URL (user ids, job ids): never lets it change the path. */
const seg = encodeURIComponent

export const api = {
  config: () => get<AppConfig>('/api/config'),
  wall: () => get<WallState>('/api/wall'),
  ambient: (user: string) => get<Ambient>(`/api/users/${seg(user)}/ambient`),
  select: (user_id: string) => post('/api/wall/select', { user_id }),
  dismiss: (session_id: string) => post('/api/wall/dismiss', { session_id }),
  session: (id: string) => get<SessionDetail>(`/api/sessions/${seg(id)}`),
  sessions: (user: string, sport?: string, limit = 60) =>
    get<(Session & { verdict: VerdictKind | null; headline: string | null })[]>(
      `/api/users/${seg(user)}/sessions?${new URLSearchParams({ limit: String(limit), ...(sport ? { sport } : {}) })}`),
  pmc: (user: string, days = 180) => get<PmcDay[]>(`/api/users/${seg(user)}/pmc?days=${days}`),
  health: (user: string, days = 90) => get<HealthDay[]>(`/api/users/${seg(user)}/health?days=${days}`),
  validation: (user: string) => get<Validation>(`/api/users/${seg(user)}/validation`),
  profile: (user: string) => get<Profile>(`/api/users/${seg(user)}/profile`),
  accounts: () => get<Account[]>('/api/accounts'),
  connect: (email: string, password: string) => post<Job>('/api/accounts', { email, password }),
  job: (id: string) => get<Job>(`/api/jobs/${seg(id)}`),
  mfa: (id: string, code: string) => post<{ ok: boolean }>(`/api/jobs/${seg(id)}/mfa`, { code }),
  syncNow: (user: string) => post<Job>(`/api/users/${seg(user)}/sync`, {}),
  morning: () => post<{ started: Job[]; pending: boolean }>('/api/wall/morning', {}),
  activityCheck: () => get<ActivityCheck>('/api/settings/activity-check'),
  setActivityCheck: (enabled: boolean) => post<ActivityCheck>('/api/settings/activity-check', { enabled }),
  buddySettings: () => get<BuddySettings>('/api/settings/buddy'),
  setBuddy: (user_id: string, animal: string) => post<BuddySettings>('/api/settings/buddy', { user_id, animal }),
}
