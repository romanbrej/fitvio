import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import './Buddy.css'

export type Animal = 'mouse' | 'cat' | 'bunny' | 'fox' | 'bear' | 'penguin' | 'frog' | 'hedgehog'
export type Mood = 'happy' | 'content' | 'sleepy' | 'overjoyed' | 'hungry' | 'asleep'
export const ANIMALS: Animal[] = ['mouse', 'cat', 'bunny', 'fox', 'bear', 'penguin', 'frog', 'hedgehog']

const BAND = '#d4ff3a'
const INK = '#141821'
const band = (y: number, color = BAND) =>
  <path d={`M50 ${y} C68 ${y - 16} 132 ${y - 16} 150 ${y} L148 ${y + 12} C130 ${y - 2} 70 ${y - 2} 52 ${y + 12} Z`} fill={color} />
const shadow = (rx = 52) => <ellipse cx="100" cy="190" rx={rx} ry="7" fill="#0b0e14" opacity="0.6" />
const cheeks = (y: number, x = 28, r = 8) => <>
  <circle cx={100 - x} cy={y} r={r} fill="#ff9fbd" opacity="0.6" /><circle cx={100 + x} cy={y} r={r} fill="#ff9fbd" opacity="0.6" />
</>

/** Each animal's own shapes (everything but the eyes and mouth) and where its face sits. */
const ANIMAL: Record<Animal, { body: ReactNode; eyes: [number, number, number]; eyeScale?: number; mouthY: number }> = {
  mouse: {
    eyes: [80, 120, 92], mouthY: 114,
    body: <>
      {shadow()}
      <path d="M144 166 C182 168 190 128 164 118 C150 113 146 128 158 132" fill="none" stroke="#9aa6b5" strokeWidth="6" strokeLinecap="round" />
      <ellipse cx="100" cy="148" rx="48" ry="40" fill="#b8c2cf" /><ellipse cx="100" cy="156" rx="30" ry="26" fill="#e6ebf1" />
      <ellipse cx="76" cy="184" rx="14" ry="7" fill="#c8d1dc" /><ellipse cx="124" cy="184" rx="14" ry="7" fill="#c8d1dc" />
      <circle cx="56" cy="50" r="32" fill="#b8c2cf" /><circle cx="56" cy="50" r="20" fill="#ffb3c7" />
      <circle cx="144" cy="50" r="32" fill="#b8c2cf" /><circle cx="144" cy="50" r="20" fill="#ffb3c7" />
      <ellipse cx="100" cy="92" rx="54" ry="47" fill="#c8d1dc" />
      {band(72)}{cheeks(108)}
      <ellipse cx="100" cy="106" rx="7" ry="5" fill="#ff7a9a" />
      <path d="M60 104 L80 108 M60 114 L80 112 M140 104 L120 108 M140 114 L120 112" stroke="#8e9aab" strokeWidth="2" strokeLinecap="round" />
    </>,
  },
  cat: {
    eyes: [80, 120, 94], mouthY: 115,
    body: <>
      {shadow()}
      <path d="M146 168 C186 160 182 112 164 104" fill="none" stroke="#e0904a" strokeWidth="12" strokeLinecap="round" />
      <ellipse cx="100" cy="148" rx="46" ry="38" fill="#f2a65a" /><ellipse cx="100" cy="158" rx="28" ry="22" fill="#fde3c8" />
      <ellipse cx="76" cy="184" rx="14" ry="7" fill="#f8c08a" /><ellipse cx="124" cy="184" rx="14" ry="7" fill="#f8c08a" />
      <path d="M50 76 L56 22 L94 52 Z" fill="#f2a65a" /><path d="M60 64 L63 36 L84 54 Z" fill="#ffb3c7" />
      <path d="M150 76 L144 22 L106 52 Z" fill="#f2a65a" /><path d="M140 64 L137 36 L116 54 Z" fill="#ffb3c7" />
      <ellipse cx="100" cy="94" rx="54" ry="46" fill="#f2a65a" />
      {band(74)}
      <path d="M48 100 L62 102 M48 110 L62 108 M152 100 L138 102 M152 110 L138 108" stroke="#d9843c" strokeWidth="4" strokeLinecap="round" />
      <ellipse cx="100" cy="112" rx="18" ry="12" fill="#fde3c8" />
      {cheeks(110)}
      <path d="M95 104 L105 104 L100 110 Z" fill="#ff7a9a" />
      <path d="M64 108 L82 110 M64 116 L82 114 M136 108 L118 110 M136 116 L118 114" stroke="#8a5a2c" strokeWidth="2" strokeLinecap="round" />
    </>,
  },
  bunny: {
    eyes: [80, 120, 98], mouthY: 112,
    body: <>
      {shadow()}
      <circle cx="150" cy="162" r="14" fill="#ffffff" />
      <ellipse cx="100" cy="150" rx="46" ry="38" fill="#e6ebf1" /><ellipse cx="100" cy="158" rx="28" ry="24" fill="#ffffff" />
      <ellipse cx="76" cy="184" rx="15" ry="7" fill="#f4f6f8" /><ellipse cx="124" cy="184" rx="15" ry="7" fill="#f4f6f8" />
      <ellipse cx="80" cy="36" rx="14" ry="38" fill="#eef2f6" transform="rotate(-12 80 36)" />
      <ellipse cx="80" cy="38" rx="7" ry="28" fill="#ffb3c7" transform="rotate(-12 80 38)" />
      <ellipse cx="120" cy="36" rx="14" ry="38" fill="#eef2f6" transform="rotate(12 120 36)" />
      <ellipse cx="120" cy="38" rx="7" ry="28" fill="#ffb3c7" transform="rotate(12 120 38)" />
      <ellipse cx="100" cy="96" rx="52" ry="44" fill="#eef2f6" />
      {band(78)}{cheeks(110)}
      <ellipse cx="100" cy="107" rx="6" ry="4.5" fill="#ff7a9a" />
      <rect x="96" y="120" width="8" height="8" rx="2" fill="#ffffff" stroke="#c9d1dc" strokeWidth="1.5" />
    </>,
  },
  fox: {
    eyes: [80, 120, 96], mouthY: 117,
    body: <>
      {shadow()}
      <ellipse cx="160" cy="150" rx="20" ry="40" fill="#ff8a3d" transform="rotate(40 160 150)" />
      <ellipse cx="179" cy="128" rx="10" ry="14" fill="#fff3e8" transform="rotate(40 179 128)" />
      <ellipse cx="100" cy="148" rx="46" ry="38" fill="#ff8a3d" /><ellipse cx="100" cy="158" rx="26" ry="24" fill="#fff3e8" />
      <ellipse cx="76" cy="184" rx="14" ry="7" fill="#3a2a20" /><ellipse cx="124" cy="184" rx="14" ry="7" fill="#3a2a20" />
      <path d="M48 78 L56 20 L96 54 Z" fill="#ff8a3d" /><path d="M60 66 L63 36 L86 56 Z" fill="#fff3e8" />
      <path d="M152 78 L144 20 L104 54 Z" fill="#ff8a3d" /><path d="M140 66 L137 36 L114 56 Z" fill="#fff3e8" />
      <ellipse cx="100" cy="94" rx="54" ry="46" fill="#ff8a3d" />
      <path d="M48 100 Q74 132 100 116 Q126 132 152 100 Q142 140 100 140 Q58 140 48 100 Z" fill="#fff3e8" />
      {band(74)}{cheeks(112, 30)}
      <ellipse cx="100" cy="110" rx="6.5" ry="5" fill={INK} />
    </>,
  },
  bear: {
    eyes: [78, 122, 96], mouthY: 118,
    body: <>
      {shadow(54)}
      <ellipse cx="100" cy="148" rx="50" ry="40" fill="#a0734f" /><ellipse cx="100" cy="158" rx="30" ry="24" fill="#d9b48f" />
      <ellipse cx="74" cy="184" rx="16" ry="8" fill="#8a603f" /><ellipse cx="126" cy="184" rx="16" ry="8" fill="#8a603f" />
      <circle cx="56" cy="52" r="22" fill="#a0734f" /><circle cx="56" cy="52" r="12" fill="#d9b48f" />
      <circle cx="144" cy="52" r="22" fill="#a0734f" /><circle cx="144" cy="52" r="12" fill="#d9b48f" />
      <ellipse cx="100" cy="94" rx="56" ry="48" fill="#a0734f" />
      {band(76)}
      <ellipse cx="100" cy="114" rx="24" ry="17" fill="#d9b48f" />
      {cheeks(112, 32)}
      <ellipse cx="100" cy="107" rx="9" ry="6" fill={INK} />
    </>,
  },
  penguin: {
    eyes: [82, 118, 92], mouthY: 120,
    body: <>
      {shadow(50)}
      <ellipse cx="52" cy="140" rx="12" ry="28" fill="#4a5568" transform="rotate(20 52 140)" />
      <ellipse cx="148" cy="140" rx="12" ry="28" fill="#4a5568" transform="rotate(-20 148 140)" />
      <ellipse cx="100" cy="140" rx="50" ry="48" fill="#5a6678" /><ellipse cx="100" cy="150" rx="34" ry="36" fill="#f4f6f8" />
      <ellipse cx="80" cy="186" rx="14" ry="6" fill="#ffb347" /><ellipse cx="120" cy="186" rx="14" ry="6" fill="#ffb347" />
      <circle cx="100" cy="86" r="52" fill="#5a6678" />
      <path d="M100 66 C126 58 146 80 140 104 C134 124 112 128 100 120 C88 128 66 124 60 104 C54 80 74 58 100 66 Z" fill="#f4f6f8" />
      {band(66)}{cheeks(106, 28, 7)}
      <path d="M90 102 L110 102 L100 114 Z" fill="#ffb347" stroke="#f0962e" strokeWidth="2" strokeLinejoin="round" />
    </>,
  },
  frog: {
    eyes: [72, 132, 63], eyeScale: 0.75, mouthY: 110,
    body: <>
      {shadow(56)}
      <ellipse cx="62" cy="180" rx="22" ry="9" fill="#5fbf5b" /><ellipse cx="138" cy="180" rx="22" ry="9" fill="#5fbf5b" />
      <ellipse cx="100" cy="150" rx="48" ry="36" fill="#7ed37a" /><ellipse cx="100" cy="158" rx="30" ry="24" fill="#d6f5c8" />
      <circle cx="70" cy="64" r="22" fill="#7ed37a" /><circle cx="130" cy="64" r="22" fill="#7ed37a" />
      <ellipse cx="100" cy="100" rx="60" ry="40" fill="#7ed37a" />
      {band(88, '#38bdf8')}
      <circle cx="70" cy="62" r="13" fill="#ffffff" /><circle cx="130" cy="62" r="13" fill="#ffffff" />
      {cheeks(112, 38, 9)}
      <circle cx="94" cy="102" r="2" fill="#3c8a38" /><circle cx="106" cy="102" r="2" fill="#3c8a38" />
    </>,
  },
  hedgehog: {
    eyes: [82, 118, 108], mouthY: 128,
    body: <>
      {shadow(54)}
      <path d="M44 176 L34 150 L52 146 L40 122 L62 124 L56 98 L76 106 L80 84 L96 98 L104 76 L114 98 L130 84 L134 106 L154 98 L148 124 L170 122 L158 146 L176 150 L166 176 Z" fill="#7a5a44" />
      <ellipse cx="100" cy="158" rx="40" ry="28" fill="#f2d2b0" />
      <ellipse cx="80" cy="186" rx="13" ry="6" fill="#e2bb94" /><ellipse cx="120" cy="186" rx="13" ry="6" fill="#e2bb94" />
      <path d="M30 96 L24 70 L46 72 L40 48 L64 56 L66 30 L86 44 L100 20 L114 44 L134 30 L136 56 L160 48 L154 72 L176 70 L170 96 Z" fill="#7a5a44" />
      <circle cx="66" cy="76" r="10" fill="#f2d2b0" /><circle cx="134" cy="76" r="10" fill="#f2d2b0" />
      <ellipse cx="100" cy="106" rx="48" ry="38" fill="#f2d2b0" />
      <path d="M54 88 C72 74 128 74 146 88 L144 98 C126 86 74 86 56 98 Z" fill={BAND} />
      {cheeks(120)}
      <circle cx="100" cy="120" r="6" fill={INK} />
    </>,
  },
}

/** The shared mood face, placed where each animal's eyes and mouth are. */
function Face({ mood, at }: { mood: Mood; at: (typeof ANIMAL)[Animal] }) {
  const [xl, xr, y] = at.eyes
  const s = at.eyeScale ?? 1
  const m = at.mouthY
  const open = mood === 'happy' || mood === 'content' || mood === 'hungry'
  const r = (mood === 'hungry' ? 11 : mood === 'content' ? 7.5 : 9) * s
  const lid = (x: number) => mood === 'sleepy' ? `M${x - 10 * s} ${y + 2} Q${x} ${y - 2} ${x + 10 * s} ${y + 2}`
    : mood === 'overjoyed' ? `M${x - 10 * s} ${y + 4} Q${x} ${y - 10} ${x + 10 * s} ${y + 4}`
    : `M${x - 10 * s} ${y - 2} Q${x} ${y + 6} ${x + 10 * s} ${y - 2}`
  const mouth: Record<Mood, [string, string]> = {
    happy: [`M90 ${m} Q100 ${m + 10} 110 ${m}`, 'none'],
    content: [`M93 ${m + 1} Q100 ${m + 5} 107 ${m + 1}`, 'none'],
    sleepy: [`M96 ${m + 2} Q100 ${m + 6} 104 ${m + 2} Q100 ${m - 2} 96 ${m + 2} Z`, INK],
    overjoyed: [`M88 ${m - 2} Q100 ${m + 18} 112 ${m - 2} Z`, '#7a2236'],
    hungry: [`M91 ${m + 3} Q95.5 ${m - 1} 100 ${m + 3} Q104.5 ${m + 7} 109 ${m + 3}`, 'none'],
    asleep: [`M95 ${m + 1} Q100 ${m + 4} 105 ${m + 1}`, 'none'],
  }
  return <>
    {open ? <>
      <circle cx={xl} cy={y} r={r} fill={INK} /><circle cx={xr} cy={y} r={r} fill={INK} />
      <circle cx={xl + 3 * s} cy={y - 4 * s} r={(mood === 'hungry' ? 4.5 : 3) * s} fill="#fff" />
      <circle cx={xr + 3 * s} cy={y - 4 * s} r={(mood === 'hungry' ? 4.5 : 3) * s} fill="#fff" />
    </> : <path d={`${lid(xl)} ${lid(xr)}`} fill="none" stroke={INK} strokeWidth="4.5" strokeLinecap="round" />}
    <path d={mouth[mood][0]} fill={mouth[mood][1]} stroke={INK} strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
    {mood === 'overjoyed' && <g fill={BAND}>
      <path d="M24 40 l4 10 l10 4 l-10 4 l-4 10 l-4 -10 l-10 -4 l10 -4 Z" />
      <path d="M176 30 l3 7 l7 3 l-7 3 l-3 7 l-3 -7 l-7 -3 l7 -3 Z" />
      <path d="M182 92 l2 5 l5 2 l-5 2 l-2 5 l-2 -5 l-5 -2 l5 -2 Z" />
    </g>}
    {mood === 'asleep' && <g fill="#9aa4b2" fontFamily="Barlow Condensed, sans-serif" fontWeight="800" fontStyle="italic">
      <text x="150" y="40" fontSize="30">Z</text><text x="172" y="20" fontSize="20">z</text>
    </g>}
    {mood === 'sleepy' && <path d="M164 64 C164 64 156 76 156 81 C156 86 160 89 164 89 C168 89 172 86 172 81 C172 76 164 64 164 64 Z" fill="#38bdf8" />}
    {mood === 'hungry' && <g>
      <path d="M8 168 L52 168 C52 182 42 190 30 190 C18 190 8 182 8 168 Z" fill="#5a6678" />
      <path d="M4 166 L56 166" stroke="#9aa4b2" strokeWidth="4" strokeLinecap="round" />
    </g>}
  </>
}

/** The training buddy. `pettable` turns it into a button that shows hearts when tapped. */
export function Buddy({ animal, mood, size = 140, pettable = false, label }: {
  animal: Animal; mood: Mood; size?: number; pettable?: boolean; label?: string
}) {
  const a = ANIMAL[animal] ?? ANIMAL.mouse
  const [hearts, setHearts] = useState(0)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const svg = (
    <svg width={size} height={size} viewBox="0 0 200 200" role="img" aria-label={label ?? `${animal}, ${mood}`}>
      {a.body}
      <Face mood={mood} at={a} />
    </svg>
  )
  if (!pettable) return svg
  return (
    <button className="buddy-pet" aria-label={`Pet your ${animal}`} onClick={e => {
      e.stopPropagation()
      setHearts(h => h + 1)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setHearts(0), 1200)
    }}>
      {svg}
      {hearts > 0 && <span key={hearts} className="buddy-hearts" aria-hidden>
        <i>♥</i><i>♥</i><i>♥</i>
      </span>}
    </button>
  )
}
