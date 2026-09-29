import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatDate } from '../api'
import type { Run } from '../api'
import { Badge, EmptyNotice, ErrorNotice, LoadingNotice, PageTitle, Panel, StatCard } from '../ui'

type RunList = { items: Run[]; total: number; limit: number; offset: number }

export default function RunsPage() {
  const client = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => api<RunList>('/api/runs?limit=50') })
  const detail = useQuery({ queryKey: ['run', selectedId], queryFn: () => api<Run>(`/api/runs/${selectedId}`), enabled: selectedId != null })
  const runNow = useMutation({ mutationFn: () => api<Run>('/api/runs', { method: 'POST' }), onSuccess: async () => { await client.invalidateQueries({ queryKey: ['runs'] }); await client.invalidateQueries({ queryKey: ['stats'] }); await client.invalidateQueries({ queryKey: ['listings'] }); await client.invalidateQueries({ queryKey: ['dashboard'] }) } })
  const latest = runs.data?.items[0]

  return <main className="content">
    <PageTitle eyebrow="AUTOMATION HISTORY" title="Collection runs" description="See what ran, what changed, and which sources need attention." action={<button className="button button-primary" disabled={runNow.isPending} onClick={() => runNow.mutate()}>{runNow.isPending ? 'Starting…' : 'Run all profiles now'}</button>} />
    {runNow.isError && <ErrorNotice error={runNow.error} />}{runs.isError && <ErrorNotice error={runs.error} />}
    <section className="stats-grid run-stats"><StatCard label="Recorded runs" value={runs.data?.total ?? '—'} /><StatCard label="Latest status" value={latest?.status ?? '—'} tone={latest?.status === 'success' ? 'green' : 'amber'} /><StatCard label="Listings seen last run" value={latest?.listings_seen ?? '—'} /><StatCard label="Warnings + errors" value={latest ? latest.warning_count + latest.error_count : '—'} tone={latest && latest.warning_count + latest.error_count === 0 ? 'green' : 'amber'} /></section>
    <div className="runs-layout">
      <Panel title="Run history" eyebrow={`${runs.data?.total ?? 0} RECORDED`}>
        {runs.isLoading ? <LoadingNotice /> : runs.data?.items.length ? <div className="run-list">{runs.data.items.map((run) => <button className={`run-row ${selectedId === run.id ? 'selected' : ''}`} key={run.id} onClick={() => setSelectedId(run.id)}>
          <span className={`status-dot ${run.status === 'success' ? 'is-ready' : 'is-warning'}`} /><span><strong>Run #{run.id}</strong><small>{formatDate(run.started_at, { dateStyle: 'medium', timeStyle: 'short' })} · {run.trigger}</small></span><span className="run-row-count">{run.listings_seen} seen</span><Badge tone={run.status === 'success' ? 'good' : run.status === 'partial' ? 'warn' : 'bad'}>{run.status}</Badge>
        </button>)}</div> : <EmptyNotice title="No collection runs yet">Run a profile to create the first run record.</EmptyNotice>}
      </Panel>
      <Panel title={detail.data ? `Run #${detail.data.id}` : 'Run details'} eyebrow="SOURCE HEALTH">
        {detail.isLoading ? <LoadingNotice /> : detail.isError ? <ErrorNotice error={detail.error} /> : detail.data ? <div className="run-detail">
          <div className="run-detail-status"><Badge tone={detail.data.status === 'success' ? 'good' : 'warn'}>{detail.data.status}</Badge><span>{detail.data.hostname}</span></div>
          <dl className="spec-list"><div><dt>Started</dt><dd>{formatDate(detail.data.started_at, { dateStyle: 'medium', timeStyle: 'short' })}</dd></div><div><dt>Finished</dt><dd>{formatDate(detail.data.finished_at, { dateStyle: 'medium', timeStyle: 'short' })}</dd></div><div><dt>Profiles / sources</dt><dd>{detail.data.profiles_processed} / {detail.data.sources_processed}</dd></div><div><dt>Seen / new / changed</dt><dd>{detail.data.listings_seen} / {detail.data.listings_new} / {detail.data.listings_changed}</dd></div><div><dt>Price drops / removed</dt><dd>{detail.data.price_drops} / {detail.data.listings_removed}</dd></div><div><dt>Detail requests</dt><dd>{detail.data.detail_requests}</dd></div><div><dt>LLM calls / cached</dt><dd>{detail.data.llm_calls} / {detail.data.llm_cache_hits}</dd></div></dl>
          <div className="run-messages"><h3>Warnings and errors</h3>{detail.data.messages?.length ? detail.data.messages.map((message) => <div className={`run-message level-${message.level}`} key={message.id}><Badge tone={message.level === 'error' ? 'bad' : 'warn'}>{message.level}</Badge><span><strong>{message.code ?? 'Run message'}</strong><small>{message.message}</small></span></div>) : <p className="muted-copy">No warnings or errors were recorded.</p>}</div>
        </div> : <EmptyNotice title="Select a run">Choose a row to inspect its metrics and recorded messages.</EmptyNotice>}
      </Panel>
    </div>
  </main>
}
