import { useSyncExternalStore } from 'react'

/** Metric or imperial, per person (backend/fitvio/units.py). Every number from the API is metric (m, s/km,
 *  m/s, kg, °C); the screens turn it into the units of the person on screen right before showing it. The
 *  shells (the wall's App, PhoneApp) set them while rendering, before any screen formats a number. */
export type Units = 'metric' | 'imperial'

const KM_PER_MI = 1.609344
const M_PER_FT = 0.3048
const M_PER_YD = 0.9144
const KG_PER_LB = 0.45359237

let current: Units = 'metric'
const listeners = new Set<() => void>()

export function setUnits(u: Units | null | undefined) {
  const next = u === 'imperial' ? 'imperial' : 'metric'
  if (next === current) return
  current = next
  listeners.forEach(l => l())
}

export const units = (): Units => current
const imperial = () => current === 'imperial'

/** Re-renders a component when the units change. */
export function useUnits(): Units {
  return useSyncExternalStore(l => { listeners.add(l); return () => { listeners.delete(l) } }, units)
}

// --- unit labels ------------------------------------------------------------
export const paceUnit = () => imperial() ? '/mi' : '/km'
/** a pace difference: "s/km" or "s/mi" */
export const paceDiffUnit = () => imperial() ? 's/mi' : 's/km'
export const swimUnit = () => imperial() ? '/100 yd' : '/100 m'
export const swimDiffUnit = () => imperial() ? 's/100 yd' : 's/100 m'
export const distUnit = () => imperial() ? 'mi' : 'km'
export const speedUnit = () => imperial() ? 'mph' : 'km/h'
export const weightUnit = () => imperial() ? 'lb' : 'kg'
export const elevUnit = () => imperial() ? 'ft' : 'm'
export const tempUnit = () => imperial() ? '°F' : '°C'

// --- values (metric in, the person's units out) -----------------------------
/** seconds per km → seconds per km or mile (also for differences) */
export const perKm = (sPerKm: number) => imperial() ? sPerKm * KM_PER_MI : sPerKm
/** seconds per 100 m → seconds per 100 m or 100 yd (also for differences) */
export const per100m = (sPer100m: number) => imperial() ? sPer100m * M_PER_YD : sPer100m
/** metres → km or miles */
export const longDistance = (m: number) => imperial() ? m / 1000 / KM_PER_MI : m / 1000
/** pool metres → m or yd */
export const poolDistance = (m: number) => imperial() ? m / M_PER_YD : m
export const speedOf = (kmh: number) => imperial() ? kmh / KM_PER_MI : kmh
export const weightOf = (kg: number) => imperial() ? kg / KG_PER_LB : kg
export const elevOf = (m: number) => imperial() ? m / M_PER_FT : m
export const tempOf = (c: number) => imperial() ? c * 9 / 5 + 32 : c
/** running efficiency: metres per heartbeat → m or ft per beat */
export const perBeat = (m: number) => imperial() ? m / M_PER_FT : m

/** "28 °C" / "82 °F" */
export const temp = (c: number) => `${Math.round(tempOf(c))} ${tempUnit()}`
/** "12 km/h" / "7 mph" */
export const wind = (kmh: number) => `${Math.round(speedOf(kmh))} ${speedUnit()}`
/** "250 m" / "820 ft" */
export const elevation = (m: number) => `${Math.round(elevOf(m))} ${elevUnit()}`
/** "80.5" kg or "177.5" lb, without the unit (tables put it in the header) */
export const weightNum = (kg: number, dp = 1) => String(+weightOf(kg).toFixed(dp))
/** "80.5 kg" / "177.5 lb" */
export const weight = (kg: number, dp = 1) => `${weightNum(kg, dp)} ${weightUnit()}`
