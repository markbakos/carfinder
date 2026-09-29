import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage, formatDate, formatMoney, formatNumber, vehicleName } from '../api'
import type { Analysis, Listing, UserStateName } from '../api'
import { Badge, EmptyNotice, ErrorNotice, Field, LoadingNotice, Panel, ScorePill, scoreTone } from '../ui'

type History = {
  snapshots: Array<NonNullable<Listing['current']> & { market_value: Listing['market_value']; scores: Listing['scores'] }>
  events: Array<{ id: number; type: string; occurred_at: string; old: Record<string, unknown>; new: Record<string, unknown>; snapshot_id: number | null }>
}
type Match = { profile_id: number; profile_name: string; hard_filter_pass: boolean; profile_fit_score: number | null; rank_score: number | null }
type StateResponse = { state: UserStateName; notes: string; rejection_reason: string | null; updated_at: string | null }

const labels: Record<string, string> = {
  market_value: 'Market value', mechanical_risk: 'Mechanical risk', maintenance_evidence: 'Maintenance evidence',
  listing_transparency: 'Listing transparency', ownership_history: 'Ownership history', seller_listing_risk: 'Seller / listing risk',
}

function EvidenceList({ title, items, tone = 'neutral', empty }: {
  title: string
  items: Array<{ summary?: string; question?: string; evidence?: string; reason?: string; field?: string; priority?: string; severity?: string }>
  tone?: 'neutral' | 'good' | 'warn'
  empty: string
}) {
  return <section className={`evidence-card evidence-${tone}`}><h3>{title}</h3>{items.length ? <ul>{items.map((item, index) => <li key={`${item.field ?? item.summary ?? item.question}-${index}`}><strong>{item.summary ?? item.question ?? item.field}</strong>{item.evidence && <span>{item.evidence}</span>}{item.reason && <span>{item.reason}</span>}{(item.priority || item.severity) && <Badge tone={item.severity === 'high' || item.priority === 'high' ? 'warn' : 'neutral'}>{item.priority ?? item.severity}</Badge>}</li>)}</ul> : <p className="muted-copy">{empty}</p>}</section>
}

export default function ListingDetailPage() {
  const { listingId } = useParams()
  const id = Number(listingId)
  const client = useQueryClient()
  const listing = useQuery({ queryKey: ['listing', id], queryFn: () => api<Listing>(`/api/listings/${id}`), enabled: Number.isInteger(id) && id > 0 })
  const analysis = useQuery({ queryKey: ['analysis', id], queryFn: () => api<Analysis>(`/api/listings/${id}/analysis`), enabled: listing.isSuccess })
  const history = useQuery({ queryKey: ['history', id], queryFn: () => api<History>(`/api/listings/${id}/history`), enabled: listing.isSuccess })
  const matches = useQuery({ queryKey: ['matches', id], queryFn: () => api<Match[]>(`/api/listings/${id}/matches`), enabled: listing.isSuccess })
  const [state, setState] = useState<UserStateName>('new')
  const [notes, setNotes] = useState('')
  const [rejectionReason, setRejectionReason] = useState('')
  const [feedback, setFeedback] = useState('')
  const saveState = useMutation({ mutationFn: (body: { state: UserStateName; notes: string; rejection_reason: string | null }) => api<StateResponse>(`/api/listings/${id}/user-state`, { method: 'PATCH', body: JSON.stringify(body) }), onSuccess: async () => { setFeedback('Shopping notes saved.'); await client.invalidateQueries({ queryKey: ['listing', id] }); await client.invalidateQueries({ queryKey: ['listings'] }); await client.invalidateQueries({ queryKey: ['dashboard'] }); await client.invalidateQueries({ queryKey: ['stats'] }) } })
  const reanalyze = useMutation({ mutationFn: () => api<{ status: string }>(`/api/listings/${id}/reanalyze`, { method: 'POST' }), onSuccess: async () => { setFeedback('Analysis refreshed.'); await client.invalidateQueries({ queryKey: ['analysis', id] }); await client.invalidateQueries({ queryKey: ['listing', id] }); await client.invalidateQueries({ queryKey: ['listings'] }); await client.invalidateQueries({ queryKey: ['dashboard'] }); await client.invalidateQueries({ queryKey: ['stats'] }) } })
  const claims = useMemo(() => analysis.data?.claims ?? [], [analysis.data?.claims])

  useEffect(() => {
    if (!listing.data) return
    setState(listing.data.user_state.state)
    setNotes(listing.data.user_state.notes)
    setRejectionReason(listing.data.user_state.rejection_reason ?? '')
  }, [listing.data?.id, listing.data?.user_state.updated_at, listing.data?.user_state.notes, listing.data?.user_state.state, listing.data?.user_state.rejection_reason])

  function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveState.mutate({ state, notes, rejection_reason: state === 'rejected' && rejectionReason ? rejectionReason : null })
  }

  if (listing.isLoading) return <main className="content"><LoadingNotice label="Opening listing…" /></main>
  if (listing.isError) return <main className="content"><ErrorNotice error={listing.error} /><Link className="button button-quiet" to="/listings">Back to listings</Link></main>
  if (!listing.data) return <main className="content"><EmptyNotice title="Listing not found" /></main>
  const current = listing.data
  const snapshot = current.current
  if (!snapshot) return <main className="content"><EmptyNotice title="This listing has no saved detail snapshot" /></main>

  const photoList = snapshot.images.map((image) => typeof image === 'string' ? image : image.url).filter((url): url is string => Boolean(url)).slice(0, 5)
  const positives = analysis.data?.result?.positive_claims ?? []
  const concerns = analysis.data?.result?.concerns ?? []
  const risks = analysis.data?.result?.risk_signals ?? []
  const missing = analysis.data?.result?.missing_information ?? []
  const questions = analysis.data?.result?.questions_to_ask ?? []

  return <main className="content detail-content">
    <Link className="back-link" to="/listings">← All listings</Link>
    <div className="detail-heading">
      <div><p className="eyebrow">{snapshot.location.city ?? snapshot.location.raw ?? 'LOCAL LISTING'} · {current.provider === 'manual_import' ? 'MANUAL IMPORT' : current.provider.toUpperCase()} · FIRST SEEN {formatDate(current.first_seen_at)}</p><h1>{vehicleName(snapshot)}</h1><p className="detail-subtitle">{snapshot.vehicle.year ?? 'Year unknown'} · {formatNumber(snapshot.vehicle.mileage_km, ' km')} · {snapshot.vehicle.fuel ?? 'Fuel unknown'} · {snapshot.vehicle.transmission ?? 'Transmission unknown'}</p></div>
      <div className="detail-price"><strong>{formatMoney(snapshot.price.amount, snapshot.price.currency)}</strong><span>Last checked {formatDate(current.last_detail_fetch_at)}</span><a className="button button-quiet" href={current.url} target="_blank" rel="noreferrer">Open original listing ↗</a></div>
    </div>

    <div className="detail-top-grid">
      <div className="photo-strip">{photoList.length ? photoList.map((url, index) => <a key={`${url}-${index}`} href={url} target="_blank" rel="noreferrer" className={`detail-photo detail-photo-${index}`}><img src={url} alt={`${vehicleName(snapshot)} photo ${index + 1}`} loading={index > 1 ? 'lazy' : 'eager'} /></a>) : <div className="photo-placeholder"><span aria-hidden="true">CAR</span><p>No listing images were saved</p></div>}</div>
      <Panel title="Market comparison" eyebrow="ASKING PRICE CONTEXT" className="market-panel">
        {current.market_value?.median_amount != null ? <>
          <div className="market-main"><strong>{formatMoney(current.market_value.median_amount, snapshot.price.currency)}</strong><Badge tone={current.market_value.confidence === 'high' ? 'good' : 'warn'}>{current.market_value.confidence} confidence</Badge></div>
          <p className="muted-copy">Estimated asking-price range {formatMoney(current.market_value.range.low, snapshot.price.currency)}–{formatMoney(current.market_value.range.high, snapshot.price.currency)}</p>
          <div className="market-facts"><span><strong>{current.market_value.difference_pct == null ? '—' : `${current.market_value.difference_pct > 0 ? '+' : ''}${current.market_value.difference_pct}%`}</strong><small>vs comparable median</small></span><span><strong>{current.market_value.sample_count}</strong><small>comparables retained</small></span></div>
          <p className="market-method">Robust local asking-price median. Excluded outliers: {current.market_value.excluded_outliers}. This is not a verified transaction price.</p>
        </> : <div className="market-empty"><strong>Not enough local comparables</strong><p>{current.market_value?.sample_count ?? 0} usable listings. CarFinder requires at least 3 retained comparables before showing a market median.</p></div>}
      </Panel>
    </div>

    <div className="detail-layout">
      <div className="detail-main-column">
        <Panel title="Evidence and questions" eyebrow={`ANALYSIS · ${analysis.data?.status ?? (analysis.isLoading ? 'LOADING' : 'PENDING')}`} action={<button className="button button-quiet" disabled={reanalyze.isPending} onClick={() => reanalyze.mutate()}>{reanalyze.isPending ? 'Analyzing…' : 'Reanalyze'}</button>}>
          {analysis.isError && <ErrorNotice error={analysis.error} />}
          {analysis.data?.status === 'failed' && <div className="notice notice-error">Analysis failed. The listing and its original information are still available.</div>}
          {feedback && <div className="notice notice-success" role="status">{feedback}</div>}
          <div className="evidence-grid">
            <EvidenceList title="Positive information" items={positives} tone="good" empty="No positive claims have been extracted." />
            <EvidenceList title="Questionable information" items={[...concerns, ...risks]} tone="warn" empty="No specific concerns detected. This is not proof the car is problem-free." />
            <EvidenceList title="Important missing details" items={missing} empty="No missing details were identified." />
            <EvidenceList title="Ask the seller" items={questions} tone="neutral" empty="No follow-up questions were generated." />
          </div>
          <div className="claims-block"><div><h3>Seller claims</h3><p>Statements from the listing remain unverified unless independently checked.</p></div>{claims.length ? <ul className="claim-list">{claims.map((claim) => <li key={claim.id}><span><strong>{claim.type.replaceAll('_', ' ')}</strong><small>{claim.source_text}</small></span><Badge tone={claim.verification_status === 'verified' ? 'good' : 'warn'}>{claim.verification_status}</Badge></li>)}</ul> : <p className="muted-copy">No structured seller claims extracted.</p>}</div>
          <div className="verified-strip"><span className="verified-icon" aria-hidden="true">✓</span><span><strong>Verified facts</strong><small>{claims.some((claim) => claim.verification_status === 'verified') ? `${claims.filter((claim) => claim.verification_status === 'verified').length} independently verified claim(s)` : 'None recorded. Provider fields and seller statements are not independent verification.'}</small></span></div>
        </Panel>

        <Panel title="Original description" eyebrow="AS PROVIDED BY SELLER" className="description-panel"><div className="original-description">{snapshot.description?.trim() || 'No description was provided in the listing.'}</div></Panel>

        <Panel title="Known model-specific checks" eyebrow="REVIEWED VEHICLE KNOWLEDGE"><p className="muted-copy">No sourced checks are loaded for this exact vehicle configuration. CarFinder only applies a model issue when its generation and relevant engine are supported by reviewed sources.</p><p className="settings-help">Engine code is not identified in this listing, so engine-specific concerns remain unknown.</p></Panel>

        <Panel title="Price and listing history" eyebrow="SAVED SNAPSHOTS">
          {history.isLoading ? <LoadingNotice /> : history.isError ? <ErrorNotice error={history.error} /> : <div className="timeline">
            {history.data?.snapshots.map((item) => <div className="timeline-item" key={item.id}><span className="timeline-dot" /><div><strong>{formatMoney(item.price.amount, item.price.currency)}{item.id === snapshot.id ? ' · current' : ''}</strong><span>Observed {formatDate(item.observed_at)}</span>{item.scores?.quality_score != null && <small>Quality {item.scores.quality_score}</small>}</div></div>)}
            {history.data?.events.map((event) => <div className="timeline-item timeline-event" key={`event-${event.id}`}><span className="timeline-dot" /><div><strong>{event.type.replaceAll('_', ' ')}</strong><span>{formatDate(event.occurred_at)}</span>{Object.keys(event.old).length > 0 && <small>{JSON.stringify(event.old)} → {JSON.stringify(event.new)}</small>}</div></div>)}
            {!history.data?.snapshots.length && <EmptyNotice title="No history yet" />}
          </div>}
        </Panel>
      </div>

      <aside className="detail-side-column">
        <Panel title="Quality score" eyebrow="EVIDENCE-SUPPORTED">
          <div className="quality-summary"><ScorePill score={current.scores?.quality_score ?? null} /><span>{current.scores?.coverage_pct ?? 0}% evidence coverage</span></div>
          {current.scores?.dimensions ? <div className="dimension-list">{Object.entries(current.scores.dimensions).map(([key, dimension]) => <div className="dimension" key={key}><div className="dimension-heading"><span>{labels[key] ?? key.replaceAll('_', ' ')}</span><strong>{dimension.score == null ? 'Unscored' : dimension.score}</strong></div><div className="dimension-track"><span className={`tone-${scoreTone(dimension.score)}`} style={{ width: `${dimension.score ?? 0}%` }} /></div><p>{dimension.explanation}</p><details><summary>Scoring inputs</summary><pre>{JSON.stringify(dimension.inputs, null, 2)}</pre></details></div>)}</div> : <p className="muted-copy">Run analysis to calculate evidence-supported dimensions.</p>}
          <p className="score-note">Only supported dimensions contribute. Unknowns stay unscored; this is a research aid, not a mechanical inspection.</p>
        </Panel>

        <Panel title="Vehicle details" eyebrow="STRUCTURED LISTING DATA"><dl className="spec-list">
          {[
            ['Year', snapshot.vehicle.year], ['Mileage', formatNumber(snapshot.vehicle.mileage_km, ' km')], ['Fuel', snapshot.vehicle.fuel],
            ['Engine', snapshot.vehicle.engine_cc ? `${formatNumber(snapshot.vehicle.engine_cc, ' cc')}${snapshot.vehicle.power_kw ? ` · ${snapshot.vehicle.power_kw} kW` : ''}` : '—'],
            ['Transmission', snapshot.vehicle.transmission], ['Drivetrain', snapshot.vehicle.drive], ['Body', snapshot.vehicle.body_type],
            ['Location', snapshot.location.raw], ['Seller type', snapshot.seller_type], ['Last seen', formatDate(current.last_seen_at)],
          ].map(([label, value]) => <div key={String(label)}><dt>{label}</dt><dd>{value == null ? '—' : String(value)}</dd></div>)}
        </dl>{snapshot.features.length > 0 && <div className="feature-list">{snapshot.features.map((feature) => <Badge key={feature}>{feature.replaceAll('_', ' ')}</Badge>)}</div>}</Panel>

        <Panel title="Your decision" eyebrow="PRIVATE SHOPPING NOTES">
          <form className="state-form" onSubmit={handleSave}>
            <Field label="Shopping state"><select value={state} onChange={(event) => setState(event.target.value as UserStateName)}>{['new','watching','interested','maybe','contacted','viewing_planned','viewed','inspected','offer_made','purchased','rejected'].map((value) => <option value={value} key={value}>{value.replaceAll('_', ' ')}</option>)}</select></Field>
            {state === 'rejected' && <Field label="Reason"><select value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)}><option value="">Choose a reason</option>{['too_expensive','bad_value','mechanical_risk','too_far','suspicious','accident_history','seller_issue','wrong_spec','other'].map((value) => <option value={value} key={value}>{value.replaceAll('_', ' ')}</option>)}</select></Field>}
            <Field label="Notes"><textarea rows={5} maxLength={10000} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="What do you want to check before contacting the seller?" /></Field>
            <button className="button button-primary button-full" disabled={saveState.isPending}>{saveState.isPending ? 'Saving…' : 'Save decision'}</button>
            {saveState.isError && <span className="form-error">{errorMessage(saveState.error)}</span>}
          </form>
        </Panel>

        <Panel title="Matched searches" eyebrow="PROFILE SUITABILITY">
          {matches.isLoading ? <LoadingNotice /> : matches.isError ? <ErrorNotice error={matches.error} /> : matches.data?.length ? <div className="matched-profiles">{matches.data.map((match) => <div key={match.profile_id}><Link to={`/listings?profile=${match.profile_id}`}>{match.profile_name}</Link><span>Fit {match.profile_fit_score ?? '—'} · Rank {match.rank_score ?? '—'}</span></div>)}</div> : <p className="muted-copy">This listing has not matched a saved profile.</p>}
        </Panel>
      </aside>
    </div>
  </main>
}
