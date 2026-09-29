import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useQueries } from '@tanstack/react-query'
import { api, formatMoney, formatNumber, vehicleName } from '../api'
import type { Analysis, Listing } from '../api'
import { Badge, EmptyNotice, ErrorNotice, PageTitle, Panel, ScorePill } from '../ui'

export default function ComparePage() {
  const [params, setParams] = useSearchParams()
  const ids = useMemo(() => [...new Set((params.get('ids') ?? '').split(',').map(Number).filter((id) => Number.isInteger(id) && id > 0))].slice(0, 5), [params])
  const profile = params.get('profile')
  const listings = useQueries({ queries: ids.map((id) => ({ queryKey: ['compare-listing', id, profile], queryFn: () => api<Listing>(`/api/listings/${id}${profile ? `?profile=${encodeURIComponent(profile)}` : ''}`) })) })
  const analyses = useQueries({ queries: ids.map((id) => ({ queryKey: ['compare-analysis', id], queryFn: () => api<Analysis>(`/api/listings/${id}/analysis`) })) })
  const ready = listings.filter((query) => query.data).map((query) => query.data as Listing)

  function remove(id: number) {
    const next = ids.filter((selected) => selected !== id)
    setParams(next.length ? { ids: next.join(','), ...(profile ? { profile } : {}) } : {})
  }

  const rows: Array<{ label: string; value: (item: Listing) => string }> = [
    { label: 'Asking price', value: (item) => formatMoney(item.current?.price.amount, item.current?.price.currency) },
    { label: 'Market median', value: (item) => formatMoney(item.market_value?.median_amount, item.current?.price.currency) },
    { label: 'Difference to median', value: (item) => item.market_value?.difference_pct == null ? 'Not enough data' : `${item.market_value.difference_pct > 0 ? '+' : ''}${item.market_value.difference_pct}%` },
    { label: 'Market evidence', value: (item) => `${item.market_value?.sample_count ?? 0} comparables · ${item.market_value?.confidence ?? 'unknown'} confidence` },
    { label: 'Quality', value: (item) => item.scores?.quality_score == null ? 'Unscored' : `${item.scores.quality_score}/100 · ${item.scores.coverage_pct}% supported` },
    { label: 'Profile fit', value: (item) => item.profile_fit_score == null ? 'Select a profile in listings' : `${item.profile_fit_score}/100` },
    { label: 'Year', value: (item) => String(item.current?.vehicle.year ?? '—') },
    { label: 'Mileage', value: (item) => formatNumber(item.current?.vehicle.mileage_km, ' km') },
    { label: 'Engine', value: (item) => item.current?.vehicle.engine_cc == null ? '—' : `${formatNumber(item.current.vehicle.engine_cc, ' cc')}${item.current.vehicle.power_kw ? ` · ${item.current.vehicle.power_kw} kW` : ''}` },
    { label: 'Fuel / transmission', value: (item) => `${item.current?.vehicle.fuel ?? '—'} · ${item.current?.vehicle.transmission ?? '—'}` },
    { label: 'Location', value: (item) => item.current?.location.raw ?? item.current?.location.city ?? '—' },
    { label: 'Shopping state', value: (item) => item.user_state.state.replaceAll('_', ' ') },
  ]

  return <main className="content">
    <PageTitle eyebrow="SIDE-BY-SIDE RESEARCH" title="Compare cars" description="See the evidence and trade-offs together. CarFinder does not pick an opaque winner." action={<Link className="button button-quiet" to="/listings">Choose listings</Link>} />
    {ids.length < 2 && <EmptyNotice title="Choose at least two listings">Open Listings, select 2–5 cars, then choose Compare.</EmptyNotice>}
    {listings.some((query) => query.isError) && <ErrorNotice error={listings.find((query) => query.error)?.error} />}
    {ids.length >= 2 && ready.length === 0 && listings.some((query) => query.isLoading) && <div className="loading-notice">Loading selected cars…</div>}
    {ready.length > 0 && <Panel title={`${ready.length} selected cars`} eyebrow="COMPARISON TABLE" className="comparison-panel"><div className="comparison-scroll"><table className="comparison-table"><thead><tr><th scope="col">Attribute</th>{ready.map((item) => <th scope="col" key={item.id}><div className="compare-heading"><Link to={`/listings/${item.id}`}>{vehicleName(item.current)}</Link><button className="icon-button" aria-label={`Remove ${vehicleName(item.current)} from comparison`} onClick={() => remove(item.id)}>×</button></div><ScorePill score={item.scores?.quality_score ?? null} /></th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.label}><th scope="row">{row.label}</th>{ready.map((item) => <td key={item.id}>{row.value(item)}</td>)}</tr>)}
        <tr><th scope="row">Concerns</th>{ready.map((item) => { const index = ids.indexOf(item.id); const concerns = analyses[index]?.data?.result?.concerns ?? []; return <td key={item.id}>{concerns.length ? <ul className="compare-concerns">{concerns.slice(0, 4).map((concern, i) => <li key={`${concern.category}-${i}`}><Badge tone="warn">{concern.severity}</Badge> {concern.summary}</li>)}</ul> : <span className="muted-copy">No specific concern extracted</span>}</td> })}</tr>
        <tr><th scope="row">Quality dimensions</th>{ready.map((item) => <td key={item.id}><ul className="compare-dimensions">{Object.entries(item.scores?.dimensions ?? {}).map(([key, dimension]) => <li key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{dimension.score ?? '—'}</strong></li>)}</ul></td>)}</tr>
      </tbody></table></div></Panel>}
  </main>
}
