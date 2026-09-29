import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage } from '../api'
import type { Profile, Run } from '../api'
import { Badge, EmptyNotice, ErrorNotice, Field, LoadingNotice, PageTitle, Panel } from '../ui'

const primaryListFields = [
  ['makes', 'Makes'], ['models', 'Models'], ['generations', 'Generations'], ['fuel', 'Fuel'],
  ['transmission', 'Transmission'], ['body_type', 'Body types'],
] as const
const advancedListFields = [
  ['regions', 'Regions'], ['seller_type', 'Seller type'], ['vehicle_origin', 'Vehicle origin'], ['damage', 'Damage'],
] as const
const primaryRangeFields = [
  ['year', 'Year', 'year'], ['price', 'Price', 'amount'], ['mileage_km', 'Mileage (km)', 'km'],
] as const
const advancedRangeFields = [
  ['engine_cc', 'Engine size (cc)', 'cc'], ['power_kw', 'Power (kW)', 'kW'],
] as const
const preferenceLists = [
  ['fuel', 'Preferred fuel'], ['transmission', 'Preferred transmission'],
  ['body_type', 'Preferred body type'], ['location', 'Preferred location'], ['equipment', 'Preferred equipment'],
] as const

type Draft = {
  name: string
  sources: Array<{ provider: string; search_url: string; enabled: boolean; settings: Record<string, unknown> }>
  enabled: boolean
  initialImportMode: Profile['initial_import_mode']
  lists: Record<string, string>
  ranges: Record<string, { min: string; max: string; currency: string }>
  idealMileage: string
  idealPrice: string
  preferredMinDiscount: string
  preferences: Record<string, string>
}

const asObject = (value: unknown): Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}
const asText = (value: unknown): string => value == null ? '' : String(value)
const splitValues = (value: string): string[] => value.split(',').map((item) => item.trim()).filter(Boolean)
const joinedValues = (value: unknown): string => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string').join(', ') : ''

function profileSummary(profile: Profile): string[] {
  const summary = ['makes', 'models', 'generations', 'fuel'].flatMap((key) => {
    const values = profile.filters[key]
    return Array.isArray(values) && values.length ? [values.slice(0, 3).join(', ')] : []
  })
  for (const key of ['price', 'year', 'mileage_km']) {
    const range = asObject(profile.filters[key])
    const unit = key === 'price' ? ` ${asText(range.currency) || 'EUR'}` : key === 'mileage_km' ? ' km' : ''
    if (range.min != null || range.max != null) summary.push(`${key === 'mileage_km' ? 'Mileage' : key[0].toUpperCase() + key.slice(1)} ${range.min ?? '—'}–${range.max ?? '—'}${unit}`)
  }
  if (!summary.length && profile.sources.some((source) => source.search_url)) summary.push('Advanced provider URL')
  return summary.slice(0, 4)
}

function rangeDraft(filters: Record<string, unknown>, key: string): Draft['ranges'][string] {
  const range = asObject(filters[key])
  return { min: asText(range.min), max: asText(range.max), currency: asText(range.currency) || 'EUR' }
}

function makeDraft(profile?: Profile): Draft {
  const filters = profile?.filters ?? {}
  const preferences = profile?.preferences ?? {}
  const mileagePreference = asObject(preferences.mileage_km)
  const pricePreference = asObject(preferences.price)
  const discountPreference = asObject(preferences.market_discount)
  return {
    name: profile?.name ?? '',
    sources: profile?.sources.length
      ? profile.sources.map(({ provider, search_url, enabled, settings }) => ({ provider, search_url: search_url ?? '', enabled, settings }))
      : [{ provider: 'polovniautomobili', search_url: '', enabled: true, settings: {} }],
    enabled: profile?.enabled ?? true,
    initialImportMode: profile?.initial_import_mode ?? 'seed_only',
    lists: Object.fromEntries([...primaryListFields, ...advancedListFields].map(([key]) => [key, joinedValues(filters[key])])),
    ranges: Object.fromEntries([...primaryRangeFields, ...advancedRangeFields].map(([key]) => [key, rangeDraft(filters, key)])),
    idealMileage: asText(mileagePreference.ideal_max),
    idealPrice: asText(pricePreference.ideal_max),
    preferredMinDiscount: asText(discountPreference.preferred_min_pct),
    preferences: Object.fromEntries(preferenceLists.map(([key]) => [key, joinedValues(asObject(preferences[key]).prefer)])),
  }
}

function payloadFromDraft(draft: Draft) {
  const filters: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(draft.lists)) {
    const values = splitValues(value)
    if (values.length) filters[key] = values
  }
  for (const [key, range] of Object.entries(draft.ranges)) {
    const min = range.min === '' ? undefined : Number(range.min)
    const max = range.max === '' ? undefined : Number(range.max)
    if (min !== undefined || max !== undefined) filters[key] = { ...(min !== undefined ? { min } : {}), ...(max !== undefined ? { max } : {}), ...(key === 'price' ? { currency: range.currency } : {}) }
  }
  const preferences: Record<string, unknown> = {}
  if (draft.idealMileage !== '') preferences.mileage_km = { ideal_max: Number(draft.idealMileage) }
  if (draft.idealPrice !== '') preferences.price = { ideal_max: Number(draft.idealPrice), currency: 'EUR' }
  if (draft.preferredMinDiscount !== '') preferences.market_discount = { preferred_min_pct: Number(draft.preferredMinDiscount) }
  for (const [key, value] of Object.entries(draft.preferences)) {
    const prefer = splitValues(value)
    if (prefer.length) preferences[key] = { prefer }
  }
  return {
    name: draft.name.trim(), enabled: draft.enabled, filters, preferences,
    initial_import_mode: draft.initialImportMode,
    sources: draft.sources.map((source) => ({ ...source, search_url: source.search_url.trim() || null })),
  }
}

export default function ProfilesPage() {
  const client = useQueryClient()
  const profiles = useQuery({ queryKey: ['profiles'], queryFn: () => api<Profile[]>('/api/profiles') })
  const providers = useQuery({ queryKey: ['providers'], queryFn: () => api<Array<{ id: string; capabilities: { supports_search_url: boolean } }>>('/api/providers') })
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [draft, setDraft] = useState<Draft>(() => makeDraft())
  const [feedback, setFeedback] = useState('')
  const invalidate = () => client.invalidateQueries({ queryKey: ['profiles'] })
  const save = useMutation({
    mutationFn: () => editing === 'new'
      ? api<Profile>('/api/profiles', { method: 'POST', body: JSON.stringify(payloadFromDraft(draft)) })
      : api<Profile>(`/api/profiles/${editing}`, { method: 'PATCH', body: JSON.stringify(payloadFromDraft(draft)) }),
    onSuccess: async () => { setEditing(null); setFeedback('Profile saved.'); await invalidate() },
  })
  const toggle = useMutation({ mutationFn: ({ profile, enabled }: { profile: Profile; enabled: boolean }) => api<Profile>(`/api/profiles/${profile.id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }), onSuccess: invalidate })
  const duplicate = useMutation({ mutationFn: (profile: Profile) => api<Profile>('/api/profiles', { method: 'POST', body: JSON.stringify({
    name: `${profile.name} copy`, filters: profile.filters, preferences: profile.preferences,
    initial_import_mode: profile.initial_import_mode, sources: profile.sources.map((source) => ({ provider: source.provider, search_url: source.search_url, enabled: source.enabled, settings: source.settings })),
  }) }), onSuccess: invalidate })
  const run = useMutation({ mutationFn: (profile: Profile) => api<Run>(`/api/profiles/${profile.id}/run`, { method: 'POST' }), onSuccess: async (result) => { setFeedback(`Run ${result.status}: ${result.listings_seen} listings seen.`); await client.invalidateQueries() } })

  function startNew() { setDraft(makeDraft()); setEditing('new'); setFeedback('') }
  function startEdit(profile: Profile) { setDraft(makeDraft(profile)); setEditing(profile.id); setFeedback('') }
  function updateList(key: string, value: string) { setDraft((current) => ({ ...current, lists: { ...current.lists, [key]: value } })) }
  function updateRange(key: string, part: 'min' | 'max' | 'currency', value: string) {
    setDraft((current) => ({ ...current, ranges: { ...current.ranges, [key]: { ...current.ranges[key], [part]: value } } }))
  }
  function updatePreference(key: string, value: string) { setDraft((current) => ({ ...current, preferences: { ...current.preferences, [key]: value } })) }
  function updateSource(index: number, patch: Partial<Draft['sources'][number]>) {
    setDraft((current) => ({ ...current, sources: current.sources.map((source, sourceIndex) => sourceIndex === index ? { ...source, ...patch } : source) }))
  }
  function addSource() {
    const provider = providers.data?.[0]?.id ?? 'polovniautomobili'
    setDraft((current) => ({ ...current, sources: [...current.sources, { provider, search_url: '', enabled: true, settings: {} }] }))
  }
  function handleSave(event: FormEvent<HTMLFormElement>) { event.preventDefault(); save.mutate() }

  return <main className="content">
    <PageTitle eyebrow="REPEATABLE SEARCHES" title="Search profiles" description="Hard filters decide what belongs in a search. Preferences help rank it without hiding listings." action={<button className="button button-primary" onClick={startNew}>＋ New profile</button>} />
    {feedback && <div className="notice notice-success" role="status">{feedback}</div>}
    {save.isError && <ErrorNotice error={save.error} />}{toggle.isError && <ErrorNotice error={toggle.error} />}{duplicate.isError && <ErrorNotice error={duplicate.error} />}{run.isError && <ErrorNotice error={run.error} />}

    {editing !== null && <Panel title={editing === 'new' ? 'Create a search profile' : 'Edit search profile'} eyebrow="PROFILE EDITOR" className="editor-panel" action={<button className="button button-quiet" onClick={() => setEditing(null)}>Cancel</button>}>
      <form onSubmit={handleSave} className="profile-form">
        <div className="profile-section"><h3>What cars are you looking for?</h3><p>Leave a field empty to keep that filter open. Commas mean any of those values.</p>
          <Field label="Profile name"><input required maxLength={120} value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} placeholder="Golf V diesel" /></Field>
          <div className="filter-grid profile-list-fields">{primaryListFields.map(([key, label]) => <Field label={label} key={key} hint="Optional · comma-separated"><input value={draft.lists[key] ?? ''} onChange={(event) => updateList(key, event.target.value)} placeholder={`Any ${label.toLowerCase()}`} /></Field>)}</div>
          <div className="range-editor-grid">{primaryRangeFields.map(([key, label, unit]) => <div className="range-field" key={key}>
            <strong>{label}</strong><Field label="From"><input type="number" min="0" value={draft.ranges[key]?.min ?? ''} onChange={(event) => updateRange(key, 'min', event.target.value)} /></Field><Field label="To"><input type="number" min="0" value={draft.ranges[key]?.max ?? ''} onChange={(event) => updateRange(key, 'max', event.target.value)} /></Field>
            {key === 'price' && <Field label="Currency"><select value={draft.ranges.price?.currency ?? 'EUR'} onChange={(event) => updateRange('price', 'currency', event.target.value)}><option>EUR</option><option>RSD</option></select></Field>}
            <small>{unit}</small>
          </div>)}</div>
          <details className="profile-details"><summary>More vehicle filters</summary><div className="filter-grid profile-list-fields">{advancedListFields.map(([key, label]) => <Field label={label} key={key} hint="Optional · comma-separated"><input value={draft.lists[key] ?? ''} onChange={(event) => updateList(key, event.target.value)} /></Field>)}</div><div className="range-editor-grid">{advancedRangeFields.map(([key, label, unit]) => <div className="range-field" key={key}><strong>{label}</strong><Field label="From"><input type="number" min="0" value={draft.ranges[key]?.min ?? ''} onChange={(event) => updateRange(key, 'min', event.target.value)} /></Field><Field label="To"><input type="number" min="0" value={draft.ranges[key]?.max ?? ''} onChange={(event) => updateRange(key, 'max', event.target.value)} /></Field><small>{unit}</small></div>)}</div></details>
        </div>
        <details className="profile-details"><summary>Soft preferences and first scan</summary><p>Preferences change suitability scores but never hide listings.</p>
          <div className="filter-grid profile-list-fields">{preferenceLists.map(([key, label]) => <Field label={label} key={key} hint="Comma-separated"><input value={draft.preferences[key] ?? ''} onChange={(event) => updatePreference(key, event.target.value)} /></Field>)}
            <Field label="Ideal mileage up to (km)"><input type="number" min="0" value={draft.idealMileage} onChange={(event) => setDraft((current) => ({ ...current, idealMileage: event.target.value }))} /></Field>
            <Field label="Ideal price up to (EUR)"><input type="number" min="0" value={draft.idealPrice} onChange={(event) => setDraft((current) => ({ ...current, idealPrice: event.target.value }))} /></Field>
            <Field label="Preferred minimum discount (%)"><input type="number" min="0" max="100" value={draft.preferredMinDiscount} onChange={(event) => setDraft((current) => ({ ...current, preferredMinDiscount: event.target.value }))} /></Field>
            <Field label="First scan behavior"><select value={draft.initialImportMode} onChange={(event) => setDraft((current) => ({ ...current, initialImportMode: event.target.value as Draft['initialImportMode'] }))}><option value="seed_only">Save listings, analyze later</option><option value="analyze_all">Analyze all results</option><option value="analyze_top_n">Analyze top 25</option></select></Field>
          </div>
        </details>
        <div className="profile-section"><h3>Marketplace searches</h3><p>Each search is saved with this profile. Use the provider's search page for its full filter set; CarFinder checks every result page automatically. Very broad searches can take a while.</p>
          {draft.sources.map((source, index) => {
            const provider = providers.data?.find((item) => item.id === source.provider)
            const label = source.provider === 'polovniautomobili' ? 'PolovniAutomobili' : source.provider
            return <div className="provider-source-editor" key={`${source.provider}-${index}`}>
              <div className="filter-grid filter-grid-main"><Field label="Marketplace"><select value={source.provider} onChange={(event) => updateSource(index, { provider: event.target.value, search_url: '' })}>{(providers.data ?? [{ id: source.provider, capabilities: { supports_search_url: true } }]).map((item) => <option key={item.id} value={item.id}>{item.id === 'polovniautomobili' ? 'PolovniAutomobili' : item.id}</option>)}</select></Field><label className="check-field"><input type="checkbox" checked={source.enabled} onChange={(event) => updateSource(index, { enabled: event.target.checked })} /><span>Include this search</span></label><button type="button" className="button button-quiet" onClick={() => setDraft((current) => ({ ...current, sources: current.sources.filter((_, sourceIndex) => sourceIndex !== index) }))}>Remove search</button></div>
              {provider?.capabilities.supports_search_url !== false && <Field label={`${label} search URL`} hint="Paste the complete filtered-search link. All provider filters in that link are retained."><textarea rows={2} value={source.search_url} onChange={(event) => updateSource(index, { search_url: event.target.value })} placeholder="https://www.polovniautomobili.com/auto-oglasi/pretraga…" /></Field>}
            </div>
          })}
          <button type="button" className="button button-quiet" onClick={addSource}>＋ Add another marketplace search</button>
          <p><a href="https://www.polovniautomobili.com/auto-oglasi/pretraga" target="_blank" rel="noreferrer">Open PolovniAutomobili search ↗</a> to set detailed filters, then paste its URL above.</p>
        </div>
        {editing === 'new' && <label className="check-field"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))} /><span>Enable this profile</span></label>}
        <div className="form-footer"><span className="form-error">{save.isError ? errorMessage(save.error) : ''}</span><button className="button button-primary" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save profile'}</button></div>
      </form>
    </Panel>}

    <Panel title="Your searches" eyebrow={`${profiles.data?.length ?? '—'} SAVED PROFILES`}>
      {profiles.isLoading ? <LoadingNotice label="Loading saved profiles…" /> : profiles.isError ? <ErrorNotice error={profiles.error} /> : profiles.data?.length ? <div className="profile-list">{profiles.data.map((profile) => <article className="profile-card" key={profile.id}>
        <div className="profile-card-main"><span className={`profile-dot ${profile.enabled ? 'enabled' : ''}`} /><div><h3>{profile.name}</h3><p>{profile.sources.length ? `${profile.sources.length} provider source${profile.sources.length === 1 ? '' : 's'}` : 'No sources'} · {Object.keys(profile.filters).length} hard filter dimensions · {Object.keys(profile.preferences).length} preferences</p>
          <div className="profile-tags">{profile.enabled ? <Badge tone="good">Enabled</Badge> : <Badge>Paused</Badge>}<Badge>{profile.initial_import_mode.replaceAll('_', ' ')}</Badge>{profile.sources.map((source) => <Badge key={source.id}>{source.provider}</Badge>)}{profileSummary(profile).map((value) => <Badge key={value}>{value}</Badge>)}</div>
        </div></div>
        <div className="profile-actions"><button className="button button-quiet" onClick={() => startEdit(profile)}>Edit</button><button className="button button-quiet" onClick={() => toggle.mutate({ profile, enabled: !profile.enabled })}>{profile.enabled ? 'Disable' : 'Enable'}</button><button className="button button-quiet" onClick={() => duplicate.mutate(profile)}>Duplicate</button><button className="button button-primary" disabled={!profile.enabled || run.isPending} onClick={() => run.mutate(profile)}>Run now</button></div>
      </article>)}</div> : <EmptyNotice title="No saved searches yet">Create a profile for a focused car or a broad local-market scan.</EmptyNotice>}
    </Panel>
  </main>
}
