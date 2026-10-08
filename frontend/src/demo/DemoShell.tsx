import { ArrowLeft, ExternalLink, Monitor, Smartphone } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { REPO_URL } from './demo'
import './demo.css'

/** The demo page around the app: a landing page to pick the wall or the phone app, then a bar to switch between
 *  them. The app itself runs in an iframe (`?app`), sized like a wall tablet or a phone, so it picks its own
 *  layout exactly as on the real device. */

type View = 'wall' | 'phone'
const WALL = { w: 1280, h: 800 }   // the wall's design size (uiScale.ts)
const PHONE = { w: 390, h: 844 }   // an iPhone 14/15-sized screen
const BAR_H = 52

const viewFromUrl = (): View | null => {
  const v = new URLSearchParams(window.location.search).get('view')
  return v === 'wall' || v === 'phone' ? v : null
}

export function DemoShell() {
  const [view, setView] = useState<View | null>(viewFromUrl)
  useEffect(() => {
    const onPop = () => setView(viewFromUrl())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const go = (v: View | null) => {
    window.history.pushState(null, '', v ? `?view=${v}` : window.location.pathname)
    setView(v)
  }
  return view ? <Viewer view={view} go={go} /> : <Landing go={go} />
}

function Landing({ go }: { go: (v: View) => void }) {
  return (
    <main className="demo-landing">
      <div className="demo-brand">FITVIO</div>
      <h1>Your training and recovery, on the wall and on your phone.</h1>
      <p className="demo-lede">
        A free, self-hosted dashboard for Garmin and Intervals.icu. This demo runs on made-up data for two
        athletes, Alex and Sam. There's nothing to install, and nothing you do here is sent anywhere.
      </p>
      <div className="demo-choices">
        <button className="demo-choice" onClick={() => go('wall')}>
          <Monitor size={32} aria-hidden />
          <b>Wall display</b>
          <span>For a tablet on the wall: today's readiness, the week, and a verdict after every workout.</span>
        </button>
        <button className="demo-choice" onClick={() => go('phone')}>
          <Smartphone size={32} aria-hidden />
          <b>Phone app</b>
          <span>Your own view: trends, every session with its sets, and the training plan.</span>
        </button>
      </div>
      <p className="demo-foot">
        Runs on a Raspberry Pi or any machine with Docker; your data stays at home.{' '}
        <a href={REPO_URL} target="_blank" rel="noopener noreferrer">Get Fitvio on GitHub <ExternalLink size={14} aria-hidden /></a>
      </p>
    </main>
  )
}

function useSize(ref: React.RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ w: 0, h: 0 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return size
}

function Viewer({ view, go }: { view: View; go: (v: View | null) => void }) {
  const stage = useRef<HTMLDivElement>(null)
  const { w, h } = useSize(stage)
  return (
    <div className="demo-viewer">
      <header className="demo-bar" style={{ height: BAR_H }}>
        <button className="demo-back" onClick={() => go(null)} aria-label="Back to the demo start">
          <ArrowLeft size={18} aria-hidden /><span className="demo-brand sm">FITVIO</span>
        </button>
        <span className="demo-tag">Demo · made-up data</span>
        <div className="demo-switch" role="radiogroup" aria-label="View">
          {(['wall', 'phone'] as const).map(v => (
            <button key={v} role="radio" aria-checked={view === v} className={view === v ? 'on' : ''} onClick={() => go(v)}>
              {v === 'wall' ? <Monitor size={16} aria-hidden /> : <Smartphone size={16} aria-hidden />}
              {v === 'wall' ? 'Wall' : 'Phone'}
            </button>
          ))}
        </div>
        <a className="demo-get" href={REPO_URL} target="_blank" rel="noopener noreferrer">
          Get Fitvio <ExternalLink size={14} aria-hidden />
        </a>
      </header>
      <div className="demo-stage" ref={stage}>
        {w > 0 && (view === 'wall' ? <WallFrame w={w} h={h} /> : <PhoneFrame w={w} h={h} />)}
      </div>
    </div>
  )
}

const appSrc = `${import.meta.env.BASE_URL}?app#/`

/** Big enough: the wall fills the stage. Smaller (a phone): a 1280 × 800 wall scaled down to fit. */
function WallFrame({ w, h }: { w: number; h: number }) {
  if (w >= 1100 && h >= 640) return <iframe key="wall" className="demo-app fill" src={appSrc} title="Fitvio wall display (demo)" />
  const s = Math.min(w / WALL.w, h / WALL.h)
  return (
    <div className="demo-fit">
      <div style={{ width: WALL.w * s, height: WALL.h * s }}>
        <iframe key="wall" className="demo-app" src={appSrc} title="Fitvio wall display (demo)"
                style={{ width: WALL.w, height: WALL.h, transform: `scale(${s})`, transformOrigin: '0 0' }} />
      </div>
      {h > w && <p className="demo-hint">Turn your phone sideways for a bigger wall.</p>}
    </div>
  )
}

/** On a phone the app fills the screen; on anything wider it sits in a phone-sized frame. */
function PhoneFrame({ w, h }: { w: number; h: number }) {
  if (w < 700) return <iframe key="phone" className="demo-app fill" src={appSrc} title="Fitvio phone app (demo)" />
  const pad = 24
  const s = Math.min(1, (h - 2 * pad) / (PHONE.h + 24))
  return (
    <div className="demo-fit">
      <div style={{ width: (PHONE.w + 24) * s, height: (PHONE.h + 24) * s }}>
        <div className="demo-phone" style={{ transform: `scale(${s})`, transformOrigin: '0 0' }}>
          <iframe key="phone" className="demo-app" src={appSrc} title="Fitvio phone app (demo)"
                  style={{ width: PHONE.w, height: PHONE.h }} />
        </div>
      </div>
    </div>
  )
}
