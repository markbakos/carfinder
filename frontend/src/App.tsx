import { useQuery } from '@tanstack/react-query'
import { Route, Routes } from 'react-router'

type Health = {
  status: 'ok'
  database: 'ok'
  migration: { current: string; head: string }
}

async function getHealth(): Promise<Health> {
  const response = await fetch('/api/health')
  if (!response.ok) throw new Error(`Local API returned ${response.status}`)
  return response.json() as Promise<Health>
}

function Dashboard() {
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, retry: false })

  return (
    <main className="page-shell">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="CarFinder home">CarFinder</a>
        <span className="local-label">LOCAL DATABASE</span>
      </header>

      <section className="welcome" aria-labelledby="welcome-title">
        <p className="eyebrow">USED-CAR INTELLIGENCE</p>
        <h1 id="welcome-title">Your search starts here.</h1>
        <p className="lede">CarFinder keeps the listings you find, tracks how they change, and helps you compare the evidence.</p>
        <div className="status-line" role="status" aria-live="polite">
          <span className={`status-dot ${health.isSuccess ? 'is-ready' : ''}`} />
          {health.isLoading && 'Checking the local database…'}
          {health.isSuccess && `Database ready · migration ${health.data.migration.current}`}
          {health.isError && 'Local API is unavailable or needs initialization.'}
        </div>
      </section>

      <section className="empty-state" aria-labelledby="empty-title">
        <span className="empty-mark" aria-hidden="true">⌕</span>
        <h2 id="empty-title">No listings yet</h2>
        <p>Initialize CarFinder, then add a PolovniAutomobili search profile to begin building your local market history.</p>
        <code>carfinder init</code>
      </section>
      <footer>Runs locally · Your database stays on this machine</footer>
    </main>
  )
}

function NotFound() {
  return <main className="page-shell"><h1>Page not found</h1><a href="/">Return to CarFinder</a></main>
}

export default function App() {
  return <Routes><Route path="/" element={<Dashboard />} /><Route path="*" element={<NotFound />} /></Routes>
}
