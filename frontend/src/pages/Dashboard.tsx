import { Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { ListingQuery, Run } from '../api'
import { Badge, EmptyNotice, ErrorNotice, ListingRow, LoadingNotice, PageTitle, Panel, StatCard } from '../ui'

type Stats = {
  listings_total: number
  listings_active: number
  new_24h: number
  price_drops_7d: number
  watching: number
  strong_deals: number
  last_run: Run | null
}

export default function Dashboard() {
  const stats = useQuery({ queryKey: ['stats'], queryFn: () => api<Stats>('/api/stats') })
  const changed = useQuery({ queryKey: ['dashboard', 'changed'], queryFn: () => api<ListingQuery>('/api/listings?sort=changed&limit=5') })
  const deals = useQuery({ queryKey: ['dashboard', 'deals'], queryFn: () => api<ListingQuery>('/api/listings?minimum_score=70&sort=quality_desc&limit=5') })
  const drops = useQuery({ queryKey: ['dashboard', 'drops'], queryFn: () => api<ListingQuery>('/api/listings?price_drop=true&sort=changed&limit=4') })
  const watchlist = useQuery({ queryKey: ['dashboard', 'watchlist'], queryFn: () => api<ListingQuery>('/api/listings?user_state=watching&limit=4') })
  const recentRun = stats.data?.last_run

  return <main className="content">
    <PageTitle eyebrow="YOUR LOCAL MARKET" title="Good morning." description="A clearer view of the cars worth your attention." action={<Link className="button button-primary" to="/listings">Browse listings <span aria-hidden="true">↗</span></Link>} />
    {(stats.isError || changed.isError) && <ErrorNotice error={stats.error ?? changed.error} />}
    <section className="stats-grid" aria-label="Market summary">
      <StatCard label="Active listings" value={stats.data?.listings_active ?? '—'} note={`${stats.data?.listings_total ?? '—'} tracked over time`} />
      <StatCard label="New in 24 hours" value={stats.data?.new_24h ?? '—'} note="Recently discovered" tone="green" />
      <StatCard label="Price reductions" value={stats.data?.price_drops_7d ?? '—'} note="In the last seven days" tone="amber" />
      <StatCard label="Strong deal signals" value={stats.data?.strong_deals ?? '—'} note="Only with a useful market sample" tone="green" />
    </section>

    <div className="dashboard-grid">
      <Panel title="Recently changed" eyebrow="LATEST ACTIVITY" action={<Link className="text-link" to="/listings?sort=changed">View all <span aria-hidden="true">→</span></Link>} className="panel-wide">
        {changed.isLoading ? <LoadingNotice label="Loading recent listings…" /> : changed.data?.items.length ? <div className="listing-stack">{changed.data.items.map((item) => <ListingRow key={item.id} item={item} />)}</div> : <EmptyNotice title="No listings yet">Add a search profile and run your first scan.</EmptyNotice>}
      </Panel>
      <Panel title="Strong value signals" eyebrow="LOCAL COMPARABLES" action={<Link className="text-link" to="/listings?minimum_score=70&sort=quality_desc">Browse <span aria-hidden="true">→</span></Link>}>
        {deals.isLoading ? <LoadingNotice /> : deals.data?.items.length ? <div className="mini-list">{deals.data.items.slice(0, 4).map((item) => <Link className="mini-listing" to={`/listings/${item.id}`} key={item.id}><span className="mini-title">{item.current?.title ?? 'Listing'}</span><strong>{item.market_value?.difference_pct != null ? `${item.market_value.difference_pct}%` : '—'}</strong><small>{item.market_value?.sample_count ?? 0} comparable listings</small></Link>)}</div> : <EmptyNotice title="No supported deal signals">Scores appear when the listing data and local market sample support them.</EmptyNotice>}
      </Panel>
      <Panel title="Price drops" eyebrow="NEGOTIATION WATCH" action={<Link className="text-link" to="/listings?price_drop=true">All drops <span aria-hidden="true">→</span></Link>}>
        {drops.isLoading ? <LoadingNotice /> : drops.data?.items.length ? <div className="mini-list">{drops.data.items.slice(0, 4).map((item) => <Link className="mini-listing" to={`/listings/${item.id}`} key={item.id}><span className="mini-title">{item.current?.title ?? 'Listing'}</span><strong>{item.current ? `${item.current.price.currency ?? ''} ${item.current.price.amount?.toLocaleString('sr-RS') ?? '—'}` : '—'}</strong><small>{item.current?.location.city ?? 'Location unknown'}</small></Link>)}</div> : <EmptyNotice title="No recent price drops">A drop appears here after the provider reports a lower asking price.</EmptyNotice>}
      </Panel>
      <Panel title="Collection health" eyebrow="SCRAPER STATUS">
        {stats.isLoading ? <LoadingNotice /> : recentRun ? <div className="health-summary">
          <div className="health-status"><span className={`status-dot ${recentRun.status === 'success' ? 'is-ready' : 'is-warning'}`} /><Badge tone={recentRun.status === 'success' ? 'good' : 'warn'}>{recentRun.status}</Badge><span>Run #{recentRun.id}</span></div>
          <p>Last run {new Date(recentRun.started_at).toLocaleString('sr-RS')} · {recentRun.listings_seen} listings seen</p>
          <div className="health-numbers"><span><strong>{recentRun.listings_new}</strong> new</span><span><strong>{recentRun.price_drops}</strong> price drops</span><span><strong>{recentRun.warning_count + recentRun.error_count}</strong> issues</span></div>
          <Link className="text-link" to="/runs">Review run history <span aria-hidden="true">→</span></Link>
        </div> : <EmptyNotice title="No completed scans">Run a saved profile to see collection health here.</EmptyNotice>}
      </Panel>
      <Panel title="Your watchlist" eyebrow={`${stats.data?.watching ?? 0} CARS TO FOLLOW`} action={<Link className="text-link" to="/listings?user_state=watching">Open watchlist <span aria-hidden="true">→</span></Link>}>
        {watchlist.isLoading ? <LoadingNotice /> : watchlist.data?.items.length ? <div className="mini-list">{watchlist.data.items.slice(0, 4).map((item) => <Link className="mini-listing" to={`/listings/${item.id}`} key={item.id}><span className="mini-title">{item.current?.title ?? 'Listing'}</span><strong>{item.current ? `${item.current.price.currency ?? ''} ${item.current.price.amount?.toLocaleString('sr-RS') ?? '—'}` : '—'}</strong><small>{item.current?.location.city ?? 'Location unknown'}</small></Link>)}</div> : <EmptyNotice title="Nothing on your watchlist">Mark a listing as watching to keep it close.</EmptyNotice>}
      </Panel>
    </div>
    <footer className="app-footer">CarFinder · Runs locally · Seller statements stay labeled as claims</footer>
  </main>
}
