export type UserStateName =
  | 'new'
  | 'watching'
  | 'interested'
  | 'maybe'
  | 'rejected'
  | 'contacted'
  | 'viewing_planned'
  | 'viewed'
  | 'inspected'
  | 'offer_made'
  | 'purchased'

export type Snapshot = {
  id: number
  observed_at: string
  title: string
  description: string
  price: { amount: number | null; currency: string | null }
  vehicle: {
    make: string | null
    model: string | null
    generation: string | null
    trim: string | null
    year: number | null
    fuel: string | null
    mileage_km: number | null
    engine_cc: number | null
    power_kw: number | null
    transmission: string | null
    drive: string | null
    body_type: string | null
    doors: number | null
    seats: number | null
  }
  location: { raw: string | null; city: string | null; region: string | null }
  seller_type: string | null
  features: string[]
  condition: Record<string, unknown>
  images: Array<string | { url?: string; position?: number }>
  structured: Record<string, unknown>
}

export type Dimension = {
  score: number | null
  weight_pct: number
  inputs: Record<string, unknown>
  explanation: string
}

export type Listing = {
  id: number
  provider: string
  external_id: string
  url: string
  status: string
  first_seen_at: string
  last_seen_at: string
  last_detail_fetch_at: string | null
  removed_at: string | null
  missing_run_count: number
  current: Snapshot | null
  market_value: {
    median_amount: number | null
    range: { low: number | null; high: number | null }
    difference_pct: number | null
    sample_count: number
    excluded_outliers: number
    confidence: string
    details: Record<string, unknown>
  } | null
  scores: {
    quality_score: number | null
    coverage_pct: number
    dimensions: Record<string, Dimension>
    explanation: Record<string, unknown>
  } | null
  profile_fit_score: number | null
  rank_score: number | null
  profile_fit_explanation: {
    preferences?: Array<{ field: string; score: number; inputs: Record<string, unknown> }>
    not_evaluated?: string[]
    reason?: string
  } | null
  user_state: { state: UserStateName; notes: string; rejection_reason: string | null; updated_at: string | null }
  matched_profile_count: number
}

export type Profile = {
  id: number
  name: string
  enabled: boolean
  filters: Record<string, unknown>
  preferences: Record<string, unknown>
  initial_import_mode: 'seed_only' | 'analyze_all' | 'analyze_top_n'
  created_at: string
  updated_at: string
  sources: Array<{ id: number; provider: string; search_url: string | null; enabled: boolean; settings: Record<string, unknown> }>
}

export type Run = {
  id: number
  started_at: string
  finished_at: string | null
  status: string
  trigger: string
  hostname: string
  profiles_processed: number
  sources_processed: number
  listings_seen: number
  listings_new: number
  listings_changed: number
  price_drops: number
  listings_removed: number
  detail_requests: number
  llm_calls: number
  llm_cache_hits: number
  warning_count: number
  error_count: number
  messages?: Array<{ id: number; level: string; code: string | null; message: string; context: Record<string, unknown>; created_at: string }>
}

export type Analysis = {
  status: string
  snapshot_id: number | null
  result: {
    positive_claims?: Array<{ summary: string; evidence: string; confidence: number; category: string }>
    concerns?: Array<{ summary: string; evidence: string; severity: string; category: string }>
    missing_information?: Array<{ field: string; importance: string; reason: string }>
    questions_to_ask?: Array<{ priority: string; question: string }>
    risk_signals?: Array<{ summary: string; severity: string; evidence: string; category: string }>
  } | null
  claims: Array<{
    id: number
    type: string
    value: unknown
    source_type: string
    source_text: string
    verification_status: string
    confidence: number
  }>
}

export type ListingQuery = {
  items: Listing[]
  total: number
  limit: number
  offset: number
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
  })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = typeof body === 'object' && body !== null && 'detail' in body ? body.detail : null
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => typeof item === 'object' && item !== null && 'msg' in item
          ? String(item.msg)
          : String(item)).join('; ')
        : `Local API returned ${response.status}`
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function formatMoney(amount: number | null | undefined, currency: string | null | undefined): string {
  if (amount == null || !currency) return 'Price on request'
  return new Intl.NumberFormat('sr-RS', { style: 'currency', currency, maximumFractionDigits: 0 }).format(amount)
}

export function formatNumber(value: number | null | undefined, suffix = ''): string {
  return value == null ? '—' : `${new Intl.NumberFormat('sr-RS').format(value)}${suffix}`
}

export function formatDate(value: string | null | undefined, options: Intl.DateTimeFormatOptions = {}): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('sr-RS', { dateStyle: 'medium', ...options }).format(date)
}

export function formatRelative(value: string): string {
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return '—'
  const days = Math.max(0, Math.floor((Date.now() - time) / 86_400_000))
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 30) return `${days} days ago`
  return `${Math.floor(days / 30)} mo ago`
}

export function imageUrl(images: Snapshot['images']): string | null {
  const first = images[0]
  if (typeof first === 'string') return first
  return first?.url ?? null
}

export function vehicleName(snapshot: Snapshot | null): string {
  if (!snapshot) return 'Listing details unavailable'
  return snapshot.title?.trim() || [snapshot.vehicle.make, snapshot.vehicle.model, snapshot.vehicle.generation, snapshot.vehicle.trim]
    .filter(Boolean).join(' ') || 'Vehicle listing'
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.'
}
