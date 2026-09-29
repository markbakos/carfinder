import { NavLink, Outlet, Route, Routes } from 'react-router'
import Dashboard from './pages/Dashboard'
import ListingsPage from './pages/ListingsPage'
import ListingDetailPage from './pages/ListingDetailPage'
import ProfilesPage from './pages/ProfilesPage'
import ComparePage from './pages/ComparePage'
import RunsPage from './pages/RunsPage'
import SettingsPage from './pages/SettingsPage'

const navigation = [
  { to: '/', label: 'Overview', end: true },
  { to: '/listings', label: 'Listings' },
  { to: '/profiles', label: 'Search profiles' },
  { to: '/runs', label: 'Runs' },
]

function AppShell() {
  return <div className="app-shell">
    <aside className="sidebar">
      <NavLink className="brand" to="/" aria-label="CarFinder overview"><span className="brand-mark" aria-hidden="true">C</span><span>CarFinder<small>LOCAL MARKET INTELLIGENCE</small></span></NavLink>
      <nav className="primary-nav" aria-label="Main navigation">
        <span className="nav-caption">WORKSPACE</span>
        {navigation.map((item) => <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => `nav-link ${isActive ? 'is-active' : ''}`}>
          <span className="nav-symbol" aria-hidden="true">{item.to === '/' ? '⌂' : item.to === '/listings' ? '▤' : item.to === '/profiles' ? '⌕' : '◷'}</span>{item.label}
        </NavLink>)}
        <NavLink to="/compare" className={({ isActive }) => `nav-link ${isActive ? 'is-active' : ''}`}><span className="nav-symbol" aria-hidden="true">⇄</span>Compare</NavLink>
      </nav>
      <div className="sidebar-bottom">
        <div className="local-card"><span className="local-led" /><span><strong>Private workspace</strong><small>Stored on this device</small></span></div>
        <NavLink to="/settings" className={({ isActive }) => `nav-link nav-settings ${isActive ? 'is-active' : ''}`}><span className="nav-symbol" aria-hidden="true">⚙</span>Settings</NavLink>
      </div>
    </aside>
    <div className="app-main">
      <header className="mobile-topbar"><NavLink className="brand" to="/" aria-label="CarFinder overview"><span className="brand-mark" aria-hidden="true">C</span><span>CarFinder</span></NavLink><span className="local-label"><span className="local-led" /> LOCAL ONLY</span></header>
      <Outlet />
    </div>
  </div>
}

function NotFound() {
  return <main className="content"><div className="not-found"><p className="eyebrow">404 · NOT FOUND</p><h1>This page isn't here.</h1><NavLink className="button button-primary" to="/">Back to overview</NavLink></div></main>
}

export default function App() {
  return <Routes><Route element={<AppShell />}>
    <Route index element={<Dashboard />} />
    <Route path="listings" element={<ListingsPage />} />
    <Route path="listings/:listingId" element={<ListingDetailPage />} />
    <Route path="profiles" element={<ProfilesPage />} />
    <Route path="compare" element={<ComparePage />} />
    <Route path="runs" element={<RunsPage />} />
    <Route path="settings" element={<SettingsPage />} />
    <Route path="*" element={<NotFound />} />
  </Route></Routes>
}
