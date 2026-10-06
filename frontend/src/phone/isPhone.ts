/** Phones get their own app (bottom tabs, one person, no wall takeover). The wall tablet — 1280 × 800 or
 *  1920 × 1080 CSS px — never matches: narrow windows, or a touch screen whose short side is phone-sized
 *  (a phone turned sideways). */
const PHONE_MAX_W = 700
const PHONE_MAX_SHORT_SIDE = 500

export function isPhone(w = window.innerWidth, h = window.innerHeight): boolean {
  const coarse = window.matchMedia?.('(pointer: coarse)').matches ?? false
  return w < PHONE_MAX_W || (coarse && Math.min(w, h) < PHONE_MAX_SHORT_SIDE)
}

/** A desktop window resized across the line gets the other app (the two don't share a router). */
export function reloadWhenPhoneChanges(phone: boolean) {
  let t: number | undefined
  window.addEventListener('resize', () => {
    window.clearTimeout(t)
    t = window.setTimeout(() => { if (isPhone() !== phone) window.location.reload() }, 300)
  })
}
