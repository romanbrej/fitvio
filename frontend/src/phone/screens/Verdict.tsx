import { AlertTriangle, ChevronRight } from 'lucide-react'
import { useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api'
import { Buddy } from '../../components/Buddy'
import { SportIcon, VerdictIcon } from '../../components/icons'
import { ImprovementList, improvedCount } from '../../components/Improvements'
import { distance, num, SPORT_LABEL, TYPE_LABEL, VERDICT_LABEL, when } from '../../format'
import { useFetch } from '../../useFetch'
import { facts } from '../../views/WallVerdict'
import { seenStore, usePhone } from '../ctx'
import { Back, Card } from '../parts'
import { VERDICT_COLOR } from '../util'

/** One session's verdict on the phone: the word, what improved, why, the key numbers. No "Overview" —
 *  the phone never ends the wall's takeover. */
export function VerdictScreen() {
  const { id } = useParams()
  const { ambient } = usePhone()
  const { data: s, error } = useFetch(() => api.session(id!), [id])
  useEffect(() => { if (id) seenStore.add(id) }, [id])
  if (error) return <><Back to="/" label="Today" /><Card>Could not load the session.</Card></>
  if (!s) return <div className="ph-boot">Loading…</div>
  const v = s.verdict
  const items = s.improvements ?? []
  const b = ambient?.user_id === s.user_id ? ambient.buddy : undefined
  const color = v ? VERDICT_COLOR[v.verdict] : 'var(--text)'
  const context = v?.context.filter(c => c.kind !== 'rpe') ?? []
  return (
    <div className="ph-stack">
      <div className="ph-row">
        <Back to="/" label="Today" />
        <span className="ph-chip ph-right"><SportIcon sport={s.sport} size={16} />{SPORT_LABEL[s.sport]} · {TYPE_LABEL[s.session_type] ?? s.session_type}</span>
      </div>

      <section className="ph-section" style={{ gap: 8 }}>
        <span className="ph-label">Session complete</span>
        <div className="ph-row" style={{ alignItems: 'flex-start' }}>
          <div className="ph-grow">
            <h1 className="ph-h1">{s.name || SPORT_LABEL[s.sport]}</h1>
            <span className="ph-foot">{when(s.start_time)}{s.distance_m ? ` · ${distance(s.distance_m, s.sport)}` : ''}</span>
          </div>
          {b && <span className="ph-buddy-box"><Buddy animal={b.animal} mood={v?.verdict === 'better' ? 'overjoyed' : 'content'} size={64} pettable /></span>}
        </div>
        {v ? (
          <>
            <div className="ph-row" style={{ gap: 10 }}>
              <VerdictIcon verdict={v.verdict} size={40} strokeWidth={2.8} color={color} />
              <span className="ph-verdict-big" style={{ color }}>{VERDICT_LABEL[v.verdict]}</span>
            </div>
            <span className="ph-h3">{v.headline}</span>
            <div className="ph-row" style={{ flexWrap: 'wrap', gap: 8 }}>
              <span className="pill">Confidence: {v.confidence}</span>
              {s.rpe != null && <span className="pill">RPE {num(s.rpe)}/10</span>}
            </div>
          </>
        ) : <span className="ph-secondary">No verdict for this session.</span>}
      </section>

      {items.length > 0 && (
        <Card>
          <span className="ph-h2">You improved <span style={{ color: improvedCount(items) ? 'var(--volt)' : 'var(--inline)' }}>{improvedCount(items)}</span> of {items.length}</span>
          <ImprovementList items={items} compact />
        </Card>
      )}

      {v && v.reasons.length > 0 && (
        <section className="ph-section">
          <span className="ph-label" style={{ padding: '0 4px' }}>Why</span>
          <ul className="ph-reasons">{v.reasons.slice(0, 4).map((r, i) => <li key={i}>{r}</li>)}</ul>
          {context.map((c, i) => <span key={i} className="ph-warn"><AlertTriangle size={16} aria-hidden /> {c.text}</span>)}
        </section>
      )}

      <div className="ph-grid2">
        {facts(s).map(([k, val]) => (
          <div key={k} className="ph-card ph-stat"><span className="ph-label sm">{k}</span><b className="num">{val}</b></div>
        ))}
      </div>

      <Link to={`/session/${encodeURIComponent(s.id)}`} className="ph-btn primary">All details <ChevronRight size={20} aria-hidden /></Link>
    </div>
  )
}
