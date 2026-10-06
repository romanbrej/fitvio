/** Big screens drawn at pixel ratio 1 (e.g. a Galaxy Tab A8 in Fully Kiosk: 1920 × 1080 CSS px) would show the
 *  wall — designed for about 1280 × 800 — 1.5× too small. Zoom the whole page up so it always lays out at
 *  roughly the design size. Viewport units are ambiguous under CSS zoom, so the CSS uses --vh / --vw
 *  (1 % of the *zoomed* viewport, in px) instead of vh / vw. */
const DESIGN_W = 1280
const DESIGN_H = 800
const MIN_SCALE = 1.15  // below this, leave the page alone (laptops, the 1280-wide tablet)

export function uiScale(w = window.innerWidth, h = window.innerHeight): number {
  const s = Math.min(w / DESIGN_W, h / DESIGN_H)
  return s >= MIN_SCALE ? Math.round(s * 100) / 100 : 1
}

function apply() {
  const s = uiScale()
  const root = document.documentElement
  root.style.zoom = s === 1 ? '' : String(s)
  root.style.setProperty('--vh', `${window.innerHeight / s / 100}px`)
  root.style.setProperty('--vw', `${window.innerWidth / s / 100}px`)
}

export function applyUiScale() {
  apply()
  window.addEventListener('resize', apply)
}
