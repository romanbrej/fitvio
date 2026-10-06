import { WifiOff } from 'lucide-react'

/** The server can't be reached — almost always: not on the home Wi-Fi (Fitvio only answers there). */
export function Offline({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="ph ph-page ph-solo ph-offline">
      <div className="ph-offline-icon"><WifiOff size={48} color="var(--warn)" strokeWidth={1.8} aria-hidden /></div>
      <h1 className="ph-title">You’re not home.</h1>
      <p className="ph-body">Fitvio lives on your home server and only answers on your home Wi-Fi. Your health data never leaves the house.</p>
      <p className="ph-sub">Your workouts are safe — they sync from Garmin by themselves, and the verdict is waiting when you get back.</p>
      <button className="ph-btn primary ph-bottom" onClick={onRetry}>Try again</button>
    </div>
  )
}
