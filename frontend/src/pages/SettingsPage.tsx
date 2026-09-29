import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { Badge, ErrorNotice, Field, LoadingNotice, PageTitle, Panel } from '../ui'

type Settings = {
  config_path: string
  database_path: string
  server: { host: string; port: number }
  scraping: { detail_recheck_hours: number; removed_after_missing_runs: number; request_delay_seconds: number; max_concurrent_detail_requests: number }
  provider: { id: string; enabled: boolean; headless: boolean; browser_profile: string }
  llm: { enabled: boolean; provider: string; model: string; timeout_seconds: number }
  image_mode: string
}
type Health = { status: string; database: string; migration: { current: string; head: string } }
type Schedule = { available: boolean; enabled: boolean; active: boolean; calendar: string | null; message: string | null }

function SettingRow({ label, value }: { label: string; value: string | number | boolean }) {
  return <div className="setting-row"><dt>{label}</dt><dd>{typeof value === 'boolean' ? <Badge tone={value ? 'good' : 'neutral'}>{value ? 'Enabled' : 'Disabled'}</Badge> : value}</dd></div>
}

export default function SettingsPage() {
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<Settings>('/api/settings') })
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/api/health') })
  const schedule = useQuery({ queryKey: ['schedule'], queryFn: () => api<Schedule>('/api/schedule') })
  const [calendar, setCalendar] = useState('*-*-* 08,14,20:00:00')
  useEffect(() => {
    if (schedule.data?.calendar) setCalendar(schedule.data.calendar)
  }, [schedule.data?.calendar])
  const enableSchedule = useMutation({
    mutationFn: () => api<Schedule>('/api/schedule', { method: 'POST', body: JSON.stringify({ calendar }) }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['schedule'] }) },
  })
  const disableSchedule = useMutation({
    mutationFn: () => api<Schedule>('/api/schedule', { method: 'DELETE' }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['schedule'] }) },
  })
  return <main className="content">
    <PageTitle eyebrow="LOCAL CONFIGURATION" title="Settings" description="Create searches in Profiles, then schedule them here. Scheduled scans keep running after you close CarFinder." />
    {settings.isError && <ErrorNotice error={settings.error} />}{health.isError && <ErrorNotice error={health.error} />}{schedule.isError && <ErrorNotice error={schedule.error} />}
    {settings.isLoading ? <LoadingNotice /> : settings.data && <div className="settings-grid">
      <Panel title="Automatic scans" eyebrow="RUNS IN THE BACKGROUND">
        {schedule.isLoading ? <LoadingNotice label="Checking systemd…" /> : schedule.data && <>
          <dl className="settings-list"><SettingRow label="Timer" value={schedule.data.active ? 'Running' : schedule.data.enabled ? 'Enabled' : 'Not enabled'} /><SettingRow label="Schedule" value={schedule.data.calendar ?? 'Not installed'} /></dl>
          <p className="settings-help">The timer starts <code>carfinder run</code> as a separate process. The API, UI, and browser window can be closed.</p>
          {schedule.data.available ? <div className="schedule-controls">
            <Field label="Scan schedule"><select value={calendar} onChange={(event) => setCalendar(event.target.value)}>{schedule.data.calendar && !['*-*-* 08,14,20:00:00', '*-*-* 09:00:00'].includes(schedule.data.calendar) && <option value={schedule.data.calendar}>Current custom schedule</option>}<option value="*-*-* 08,14,20:00:00">Every day · 08:00, 14:00, 20:00</option><option value="*-*-* 09:00:00">Every day · 09:00</option></select></Field>
            <button className="button button-primary" disabled={enableSchedule.isPending} onClick={() => enableSchedule.mutate()}>{enableSchedule.isPending ? 'Saving…' : schedule.data.enabled ? 'Save schedule' : 'Enable automatic scans'}</button>
            {schedule.data.enabled && <button className="button button-quiet" disabled={disableSchedule.isPending} onClick={() => disableSchedule.mutate()}>{disableSchedule.isPending ? 'Pausing…' : 'Pause timer'}</button>}
          </div> : <p className="settings-help">{schedule.data.message ?? 'systemd is not available in this environment.'}</p>}
          {enableSchedule.isError && <ErrorNotice error={enableSchedule.error} />}{disableSchedule.isError && <ErrorNotice error={disableSchedule.error} />}
        </>}
      </Panel>
      <Panel title="Storage and server" eyebrow="LOCAL ONLY"><dl className="settings-list"><SettingRow label="Configuration file" value={settings.data.config_path} /><SettingRow label="SQLite database" value={settings.data.database_path} /><SettingRow label="API address" value={`${settings.data.server.host}:${settings.data.server.port}`} /><SettingRow label="Image caching" value={settings.data.image_mode} /></dl><p className="settings-help">The API listens on loopback by default. The SQLite database is the source of truth; scheduled scans keep working while this screen is closed.</p></Panel>
      <Panel title="PolovniAutomobili" eyebrow="ACTIVE PROVIDER"><dl className="settings-list"><SettingRow label="Provider" value={settings.data.provider.id} /><SettingRow label="Enabled" value={settings.data.provider.enabled} /><SettingRow label="Headless browser" value={settings.data.provider.headless} /><SettingRow label="Browser profile" value={settings.data.provider.browser_profile} /></dl><p className="settings-help">Request spacing and detail refresh behavior are configured in the same file. CAPTCHA challenges are recorded as provider failures.</p></Panel>
      <Panel title="Collection behavior" eyebrow="CONSERVATIVE DEFAULTS"><dl className="settings-list"><SettingRow label="Detail recheck interval" value={`${settings.data.scraping.detail_recheck_hours} hours`} /><SettingRow label="Removal threshold" value={`${settings.data.scraping.removed_after_missing_runs} successful misses`} /><SettingRow label="Request delay" value={`${settings.data.scraping.request_delay_seconds} seconds`} /><SettingRow label="Concurrent detail requests" value={settings.data.scraping.max_concurrent_detail_requests} /></dl></Panel>
      <Panel title="Optional analysis" eyebrow="LLM SETTINGS"><dl className="settings-list"><SettingRow label="LLM analysis" value={settings.data.llm.enabled} /><SettingRow label="Provider" value={settings.data.llm.provider} /><SettingRow label="Model" value={settings.data.llm.model || 'Provider default'} /><SettingRow label="Timeout" value={`${settings.data.llm.timeout_seconds} seconds`} /></dl><p className="settings-help">LLM calls are optional. Listing ingestion, deterministic findings, and scores continue when this is disabled or unavailable.</p></Panel>
      <Panel title="System status" eyebrow="DATABASE HEALTH" className="settings-wide"><dl className="settings-list"><SettingRow label="API" value={health.data?.status ?? 'Checking'} /><SettingRow label="Database" value={health.data?.database ?? 'Checking'} /><SettingRow label="Migration" value={health.data ? `${health.data.migration.current} · current` : 'Checking'} /><SettingRow label="Price display" value="Shown in the listing's original currency; no FX conversion" /><SettingRow label="Runtime" value="Local process · systemd user timer supported" /></dl></Panel>
    </div>}
    <div className="notice notice-neutral settings-config-note"><strong>First-time setup</strong><span>Install Chromium once with <code>uv run playwright install chromium</code>. Use <code>carfinder doctor</code> to check browser and database readiness. Search filters and provider URLs are set in each profile.</span></div>
  </main>
}
