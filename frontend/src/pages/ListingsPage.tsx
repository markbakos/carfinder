import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { ListingQuery, Profile, SearchFilterOptions } from '../api'
import { bodyOptions, commonMakes, fuelOptions, SearchValuePicker, transmissionOptions, uniqueSorted } from '../searchFilters'
import { EmptyNotice, ErrorNotice, Field, ListingRow, LoadingNotice, PageTitle } from '../ui'

const multiFilterFields = [
  { key: 'make', label: 'Makes' }, { key: 'model', label: 'Models' },
  { key: 'generation', label: 'Generations' }, { key: 'fuel', label: 'Fuel' },
  { key: 'transmission', label: 'Transmission' }, { key: 'body_type', label: 'Body type' },
] as const
const multiFilterKeys = multiFilterFields.map(({ key }) => key)

type Draft = Record<string, string | string[]>

function draftFromParams(params: URLSearchParams): Draft {
  const draft: Draft = Object.fromEntries(params.entries())
  for (const key of multiFilterKeys) draft[key] = params.getAll(key)
  return draft
}

export default function ListingsPage() {
  const [params, setParams] = useSearchParams()
  const queryString = params.toString()
  const [draft, setDraft] = useState<Draft>(() => draftFromParams(params))
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set())
  const profiles = useQuery({ queryKey: ['profiles'], queryFn: () => api<Profile[]>('/api/profiles') })
  const filterOptions = useQuery({ queryKey: ['filter-options'], queryFn: () => api<SearchFilterOptions>('/api/filter-options') })
  const listings = useQuery({
    queryKey: ['listings', queryString],
    queryFn: () => api<ListingQuery>(`/api/listings?${queryString || 'sort=newest'}`),
  })

  useEffect(() => setDraft(draftFromParams(params)), [queryString])

  const pageSize = listings.data?.limit ?? 50
  const page = Math.floor((listings.data?.offset ?? 0) / pageSize) + 1
  const pageCount = Math.max(1, Math.ceil((listings.data?.total ?? 0) / pageSize))
  const selected = useMemo(() => [...selectedIds], [selectedIds])
  const vehicleRows = filterOptions.data?.vehicles ?? []
  const selectedMakes = new Set(values('make').map((value) => value.toLocaleLowerCase()))
  const selectedModels = new Set(values('model').map((value) => value.toLocaleLowerCase()))
  const options: Record<string, string[]> = {
    make: uniqueSorted([...commonMakes, ...vehicleRows.map((row) => row.make)]),
    model: uniqueSorted(vehicleRows.filter((row) => !selectedMakes.size || (row.make && selectedMakes.has(row.make.toLocaleLowerCase()))).map((row) => row.model)),
    generation: uniqueSorted(vehicleRows.filter((row) =>
      (!selectedMakes.size || (row.make && selectedMakes.has(row.make.toLocaleLowerCase())))
      && (!selectedModels.size || (row.model && selectedModels.has(row.model.toLocaleLowerCase()))),
    ).map((row) => row.generation)),
    fuel: fuelOptions,
    transmission: transmissionOptions,
    body_type: bodyOptions,
  }

  function values(name: string): string[] {
    const value = draft[name]
    return Array.isArray(value) ? value : []
  }

  function text(name: string): string {
    const value = draft[name]
    return typeof value === 'string' ? value : ''
  }

  function handleChange(name: string, value: string | string[]) {
    setDraft((current) => ({ ...current, [name]: value }))
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const next = new URLSearchParams()
    for (const [key, value] of Object.entries(draft)) {
      if (Array.isArray(value)) value.forEach((item) => { if (item.trim()) next.append(key, item.trim()) })
      else if (value.trim()) next.set(key, value.trim())
    }
    next.set('limit', '50')
    next.set('offset', '0')
    setParams(next)
  }

  function handleSelect(id: number) {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else if (next.size < 5) next.add(id)
      return next
    })
  }

  function changePage(nextPage: number) {
    const next = new URLSearchParams(params)
    next.set('limit', String(pageSize))
    next.set('offset', String((nextPage - 1) * pageSize))
    setParams(next)
  }

  return <main className="content">
    <PageTitle eyebrow="YOUR INVENTORY" title="Listings" description="Every discovered car stays in your local history, even when it no longer matches a search." action={<><Link className="button button-quiet" to="/import">＋ Add listing</Link>{selected.length >= 2 ? <Link className="button button-primary" to={`/compare?ids=${selected.join(',')}${text('profile') ? `&profile=${text('profile')}` : ''}`}>Compare {selected.length} cars <span aria-hidden="true">⇄</span></Link> : <span className="selection-hint">Select 2–5 cars to compare</span>}</>} />
    <form className="filter-panel" onSubmit={handleSubmit}>
      <div className="filter-grid filter-grid-main">
        <Field label="Search listing text"><input type="search" value={text('q')} onChange={(event) => handleChange('q', event.target.value)} placeholder="Service history, engine…" /></Field>
        <Field label="Search profile"><select value={text('profile')} onChange={(event) => handleChange('profile', event.target.value)}><option value="">All listings</option>{profiles.data?.map((profile) => <option value={profile.id} key={profile.id}>{profile.name}</option>)}</select></Field>
        <Field label="Sort"><select value={text('sort') || 'newest'} onChange={(event) => handleChange('sort', event.target.value)}>
          <option value="newest">Recently found</option><option value="changed">Recently changed</option><option value="quality_desc">Quality score</option><option value="rank_desc">Profile rank</option><option value="price_asc">Price: low to high</option><option value="price_desc">Price: high to low</option>
        </select></Field>
        <Field label="Shopping state"><select value={text('user_state')} onChange={(event) => handleChange('user_state', event.target.value)}><option value="">Any state</option><option value="new">New</option><option value="watching">Watching</option><option value="interested">Interested</option><option value="maybe">Maybe</option><option value="contacted">Contacted</option><option value="viewing_planned">Viewing planned</option><option value="viewed">Viewed</option><option value="inspected">Inspected</option><option value="offer_made">Offer made</option><option value="purchased">Purchased</option><option value="rejected">Rejected</option></select></Field>
      </div>
      <div className="profile-picker-grid listing-filter-pickers">
        {multiFilterFields.map(({ key, label }) => <SearchValuePicker
          key={key}
          id={`listing-filter-${key}`}
          label={label}
          values={values(key)}
          options={options[key] ?? []}
          placeholder={`Search or choose ${label.toLowerCase()}…`}
          onChange={(next) => handleChange(key, next)}
        />)}
      </div>
      {filterOptions.isError && <p className="settings-help">Saved listing suggestions could not be loaded. You can still add any value manually.</p>}
      <div className="filter-grid filter-grid-secondary">
        <Field label="Year from"><input type="number" min="1900" max="2100" value={text('year_min')} onChange={(event) => handleChange('year_min', event.target.value)} /></Field>
        <Field label="Year to"><input type="number" min="1900" max="2100" value={text('year_max')} onChange={(event) => handleChange('year_max', event.target.value)} /></Field>
        <Field label="Price from"><input type="number" min="0" value={text('price_min')} onChange={(event) => handleChange('price_min', event.target.value)} /></Field>
        <Field label="Price to"><input type="number" min="0" value={text('price_max')} onChange={(event) => handleChange('price_max', event.target.value)} /></Field>
        <Field label="Currency"><select value={text('price_currency') || 'EUR'} onChange={(event) => handleChange('price_currency', event.target.value)}><option>EUR</option><option>RSD</option></select></Field>
        <Field label="Mileage up to (km)"><input type="number" min="0" value={text('mileage_max')} onChange={(event) => handleChange('mileage_max', event.target.value)} /></Field>
        <Field label="Minimum quality"><input type="number" min="0" max="100" value={text('minimum_score')} onChange={(event) => handleChange('minimum_score', event.target.value)} /></Field>
        <Field label="Provider"><select value={text('provider')} onChange={(event) => handleChange('provider', event.target.value)}><option value="">All providers</option><option value="polovniautomobili">PolovniAutomobili</option><option value="manual_import">Manual import</option></select></Field>
        <label className="check-field"><input type="checkbox" checked={text('price_drop') === 'true'} onChange={(event) => handleChange('price_drop', event.target.checked ? 'true' : '')} /><span>Price dropped</span></label>
      </div>
      <div className="filter-actions"><button className="button button-primary" type="submit">Apply filters</button><button className="button button-quiet" type="button" onClick={() => { setDraft(draftFromParams(new URLSearchParams('sort=newest'))); setParams({ sort: 'newest' }) }}>Clear</button><span className="results-count">{listings.data ? `${listings.data.total.toLocaleString('sr-RS')} results` : ' '}</span></div>
    </form>

    {listings.isError && <ErrorNotice error={listings.error} />}
    {listings.isLoading ? <LoadingNotice label="Loading your listings…" /> : listings.data?.items.length ? <>
      <div className="list-toolbar"><span className="eyebrow">SAVED MARKET HISTORY</span><span>{selected.length ? `${selected.length} selected · maximum 5` : 'Select cars to compare'}</span></div>
      <div className="listing-stack">{listings.data.items.map((item) => <ListingRow key={item.id} item={item} selected={selectedIds.has(item.id)} onSelect={handleSelect} />)}</div>
      <div className="pagination"><span>Page {page} of {pageCount}</span><div><button className="button button-quiet" disabled={page <= 1} onClick={() => changePage(page - 1)}>Previous</button><button className="button button-quiet" disabled={page >= pageCount} onClick={() => changePage(page + 1)}>Next</button></div></div>
    </> : <EmptyNotice title="No listings match these filters">Try widening the search or clear a filter to see more cars.</EmptyNotice>}
  </main>
}
