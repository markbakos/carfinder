import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { errorMessage, formatMoney, formatNumber, formatRelative, imageUrl, vehicleName } from './api'
import type { Listing } from './api'

export function PageTitle({ eyebrow, title, description, action }: {
  eyebrow: string
  title: string
  description?: string
  action?: ReactNode
}) {
  return <div className="page-title"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{description && <p className="lede">{description}</p>}</div>{action && <div className="page-title-action">{action}</div>}</div>
}

export function ErrorNotice({ error }: { error: unknown }) {
  return <div className="notice notice-error" role="alert"><strong>Could not load this information.</strong><span>{errorMessage(error)}</span></div>
}

export function LoadingNotice({ label = 'Loading…' }: { label?: string }) {
  return <div className="loading-notice" role="status"><span className="spinner" aria-hidden="true" />{label}</div>
}

export function EmptyNotice({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty-notice"><span className="empty-mark" aria-hidden="true">⌕</span><strong>{title}</strong>{children && <span>{children}</span>}</div>
}

export function Panel({ title, eyebrow, action, children, className = '' }: {
  title: string
  eyebrow?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return <section className={`panel ${className}`}><header className="panel-heading"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h2>{title}</h2></div>{action}</header>{children}</section>
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'bad' }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function ScorePill({ score, label = 'Quality' }: { score: number | null; label?: string }) {
  return <span className={`score-pill ${score == null ? 'score-unknown' : score >= 75 ? 'score-good' : score < 45 ? 'score-low' : 'score-mid'}`}>
    <strong>{score == null ? '—' : score}</strong><small>{label}</small>
  </span>
}

export function ListingRow({ item, selected = false, onSelect }: {
  item: Listing
  selected?: boolean
  onSelect?: (id: number) => void
}) {
  const snapshot = item.current
  if (!snapshot) return null
  const photo = imageUrl(snapshot.images)
  const delta = item.market_value?.difference_pct
  return <article className={`listing-row ${onSelect ? 'selectable' : ''}`}>
    {onSelect && <label className="select-cell"><input type="checkbox" checked={selected} onChange={() => onSelect(item.id)} aria-label={`Select ${vehicleName(snapshot)} for comparison`} /></label>}
    <Link className="listing-photo" to={`/listings/${item.id}`} aria-label={`Open ${vehicleName(snapshot)}`}>
      {photo ? <img src={photo} alt="" loading="lazy" /> : <span aria-hidden="true">CAR</span>}
    </Link>
    <div className="listing-main">
      <Link className="listing-name" to={`/listings/${item.id}`}>{vehicleName(snapshot)}</Link>
      <span className="listing-subtitle">{snapshot.vehicle.year ?? 'Year unknown'} · {formatNumber(snapshot.vehicle.mileage_km, ' km')} · {snapshot.vehicle.fuel ?? 'Fuel unknown'}</span>
      <span className="listing-subtitle">{snapshot.location.city ?? snapshot.location.raw ?? 'Location unknown'} · Seen {formatRelative(item.first_seen_at)}</span>
    </div>
    <div className="listing-price"><strong>{formatMoney(snapshot.price.amount, snapshot.price.currency)}</strong><span>{delta == null ? 'Market unknown' : `${delta > 0 ? '+' : ''}${delta}% vs median`}</span></div>
    <div className="listing-scores"><ScorePill score={item.scores?.quality_score ?? null} /><ScorePill score={item.profile_fit_score} label="Fit" /></div>
    <div className="listing-indicators">
      {item.status !== 'active' && <Badge tone="warn">{item.status}</Badge>}
      {item.market_value?.confidence && <Badge>{item.market_value.confidence} market</Badge>}
      {item.user_state.state !== 'new' && <Badge tone="good">{item.user_state.state.replaceAll('_', ' ')}</Badge>}
      <Link className="text-link" to={`/listings/${item.id}`}>Details <span aria-hidden="true">↗</span></Link>
    </div>
  </article>
}

export function StatCard({ label, value, note, tone }: { label: string; value: string | number; note?: string; tone?: 'green' | 'amber' }) {
  return <div className={`stat-card ${tone ? `stat-${tone}` : ''}`}><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}

export function scoreTone(score: number | null): 'good' | 'warn' | 'bad' | 'neutral' {
  return score == null ? 'neutral' : score >= 75 ? 'good' : score >= 45 ? 'warn' : 'bad'
}
