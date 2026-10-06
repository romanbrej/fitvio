import { createContext, useContext } from 'react'
import type { Ambient, AppConfig, Job, User } from '../api'

export interface PhoneCtx {
  config: AppConfig
  me: User
  ambient: Ambient | null
  /** the server didn't answer the last time (data on screen is older) */
  stale: boolean
  syncJob: Job | null
  syncNow: () => void
  refresh: () => Promise<void>
  reloadConfig: () => void
  setMe: (id: string | null) => void
}

export const PhoneContext = createContext<PhoneCtx | null>(null)
export const usePhone = () => useContext(PhoneContext)!

/** Who this phone belongs to — remembered on the phone only, never sent to the wall. */
const ME_KEY = 'fitvio.me'
const SEEN_KEY = 'fitvio.seenVerdicts'

export const meStore = {
  get: (): string | null => { try { return localStorage.getItem(ME_KEY) } catch { return null } },
  set: (id: string | null) => {
    try {
      if (id) localStorage.setItem(ME_KEY, id)
      else localStorage.removeItem(ME_KEY)
    } catch { /* private mode: asks again next time */ }
  },
}

/** Verdicts already opened on this phone (their hero card loses the NEW badge). */
const SEEN_MAX = 30
const readSeen = (): string[] => JSON.parse(localStorage.getItem(SEEN_KEY) ?? '[]')

export const seenStore = {
  has: (id: string): boolean => {
    try { return readSeen().includes(id) } catch { return false }
  },
  add: (id: string) => {
    try {
      const others = readSeen().filter(x => x !== id)
      localStorage.setItem(SEEN_KEY, JSON.stringify([...others, id].slice(-SEEN_MAX)))
    } catch { /* not remembered */ }
  },
}
