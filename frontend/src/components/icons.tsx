import { Activity, Bike, CircleHelp, Dumbbell, Footprints, MoveRight, TrendingDown, TrendingUp, Waves } from 'lucide-react'
import type { LucideProps } from 'lucide-react'
import type { Sport, VerdictKind } from '../api'
import { VERDICT_LABEL } from '../format'

const SPORT_ICON = { running: Footprints, cycling: Bike, swimming: Waves, strength: Dumbbell, other: Activity }
const VERDICT_ICON = { better: TrendingUp, in_line: MoveRight, worse: TrendingDown, not_comparable: CircleHelp, load_only: Activity }

export function SportIcon({ sport, ...p }: { sport: Sport } & LucideProps) {
  const I = SPORT_ICON[sport] ?? Activity
  return <I strokeWidth={2} aria-hidden {...p} />
}

export function VerdictIcon({ verdict, ...p }: { verdict: VerdictKind } & LucideProps) {
  const I = VERDICT_ICON[verdict] ?? CircleHelp
  return <I strokeWidth={2.25} aria-hidden {...p} />
}

/** Icon + word + colour — never colour alone. */
export function VerdictPill({ verdict }: { verdict: VerdictKind | null }) {
  if (!verdict) return <span className="pill faint">—</span>
  return (
    <span className={`pill tone-${verdict}`}>
      <VerdictIcon verdict={verdict} size={16} />
      {VERDICT_LABEL[verdict]}
    </span>
  )
}
