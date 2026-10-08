import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

// Every signed-in role sees the same destinations. Admin and reviewer checks
// still happen on the routes themselves, the same as before.
const DASHBOARD = { path: '/', label: 'Dashboard', icon: 'home' }

const SECTIONS = [
  {
    label: 'Sales',
    items: [
      { path: '/quotes', label: 'Quotes', icon: 'document' },
      { path: '/orders', label: 'Orders', icon: 'clipboard' },
      { path: '/customers', label: 'Customers', icon: 'users' },
      { path: '/leads', label: 'Leads', icon: 'inbox' },
      { path: '/reviews', label: 'Reviews', icon: 'check' },
      { path: '/door-configurator', label: 'Configurator', icon: 'squares' },
    ],
  },
  {
    label: 'Operations',
    items: [
      { path: '/production', label: 'Production', icon: 'calendar' },
      { path: '/install-referrals', label: 'Installs', icon: 'truck' },
      { path: '/cut-work-orders', label: 'Cut Orders', icon: 'cut' },
      { path: '/purchasing', label: 'Purchasing', icon: 'cart' },
    ],
  },
  {
    label: 'Reports',
    items: [
      { path: '/business', label: 'Business', icon: 'chart' },
      { path: '/analytics', label: 'Sales Analytics', icon: 'chart' },
      { path: '/analytics/quoting', label: 'Quoting', icon: 'chart' },
      { path: '/analytics/order-age', label: 'Order Age Tracker', icon: 'clock' },
      { path: '/weekly-email', label: 'Weekly Email', icon: 'mail' },
    ],
  },
]

const ALL_ITEMS = [DASHBOARD, ...SECTIONS.flatMap((section) => section.items), { path: '/settings', label: 'Settings' }]

function isActive(pathname, path) {
  if (path === '/settings') return pathname.startsWith('/settings')
  if (path === '/customers') return pathname === '/customers' || pathname.startsWith('/customers/')
  if (path === '/quotes') return pathname === '/quotes' || pathname.startsWith('/quotes/')
  return pathname === path
}

function pageTitle(pathname) {
  const match = ALL_ITEMS.find((item) => isActive(pathname, item.path))
  return match?.label || 'OpenDC Portal'
}

function Icon({ name }) {
  const paths = {
    home: 'M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10',
    document: 'M7 3h7l5 5v13a1 1 0 01-1 1H7a1 1 0 01-1-1V4a1 1 0 011-1zM14 3v5h5',
    clipboard: 'M9 4h6a1 1 0 011 1v1H8V5a1 1 0 011-1zM8 6H6a1 1 0 00-1 1v13a1 1 0 001 1h12a1 1 0 001-1V7a1 1 0 00-1-1h-2',
    users: 'M16 19v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M12.5 7.5a3 3 0 11-6 0 3 3 0 016 0zM20 19v-1a3.5 3.5 0 00-2.5-3.35M16 4.6a3 3 0 010 5.8',
    inbox: 'M3 13l2-8h14l2 8M3 13h5l1 2h6l1-2h5v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6z',
    check: 'M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11',
    squares: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
    calendar: 'M5 5h14a1 1 0 011 1v14H4V6a1 1 0 011-1zM4 10h16M8 3v4M16 3v4',
    truck: 'M3 7h11v10H3zM14 11h4l3 3v3h-7M6.5 19a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM17.5 19a1.5 1.5 0 100-3 1.5 1.5 0 000 3z',
    cut: 'M7 5l5 7-5 7M17 5l-5 7 5 7',
    cart: 'M3 4h2l2.2 11h11.3l1.8-7H7M9 20a1 1 0 100-2 1 1 0 000 2zM18 20a1 1 0 100-2 1 1 0 000 2z',
    chart: 'M4 19V5M4 19h16M8 16v-5M12 16V8M16 16v-3',
    clock: 'M12 7v5l3 2M12 21a9 9 0 110-18 9 9 0 010 18z',
    mail: 'M4 6h16v12H4zM4 7l8 6 8-6',
    cog: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9c.3.6.9 1 1.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z',
  }
  return (
    <svg className="h-[18px] w-[18px] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name] || paths.home} />
    </svg>
  )
}

function Logo({ className = 'h-8' }) {
  return <img src="/assets/opendc-logo.jpg" alt="Open Distribution Company" className={`${className} w-auto`} />
}

function SideNav({ pathname, onNavigate }) {
  const linkClass = (active) =>
    `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium whitespace-nowrap ${
      active
        ? 'bg-white text-odc-900 shadow-sm'
        : 'text-white/80 hover:bg-white/10 hover:text-white'
    }`

  return (
    <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-4">
      <ul>
        <li>
          <Link
            to={DASHBOARD.path}
            onClick={onNavigate}
            aria-current={isActive(pathname, DASHBOARD.path) ? 'page' : undefined}
            className={linkClass(isActive(pathname, DASHBOARD.path))}
          >
            <Icon name={DASHBOARD.icon} />
            <span className="truncate">{DASHBOARD.label}</span>
          </Link>
        </li>
      </ul>
      {SECTIONS.map((section) => {
        const sectionActive = section.items.some((item) => isActive(pathname, item.path))
        return (
          <div key={section.label} className="mt-6">
            <p className={`px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider ${sectionActive ? 'text-white' : 'text-white/60'}`}>
              {section.label}
            </p>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const active = isActive(pathname, item.path)
                return (
                  <li key={item.path}>
                    <Link
                      to={item.path}
                      onClick={onNavigate}
                      aria-current={active ? 'page' : undefined}
                      className={linkClass(active)}
                    >
                      <Icon name={item.icon} />
                      <span className="truncate">{item.label}</span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        )
      })}
    </nav>
  )
}

function AccountMenu({ user, pathname }) {
  const navigate = useNavigate()
  const { logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const name = user?.name || user?.email || 'Account'
  const firstName = name.trim().split(/\s+/)[0] || name
  const initial = name.trim().charAt(0).toUpperCase() || 'A'
  const settingsActive = isActive(pathname, '/settings')

  useEffect(() => {
    setOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!open) return undefined
    const onPointer = (event) => {
      if (ref.current && !ref.current.contains(event.target)) setOpen(false)
    }
    const onKey = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const handleLogout = () => {
    setOpen(false)
    logout()
    navigate('/login')
  }

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={`inline-flex h-11 max-w-full items-center gap-2 whitespace-nowrap rounded-full border bg-white py-1 pl-1 pr-2.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-odc-500 ${
          settingsActive ? 'border-odc-600 ring-2 ring-odc-100' : 'border-gray-200'
        }`}
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-odc-800 text-sm font-semibold text-white">
          {initial}
        </span>
        <span className="max-w-[5.5rem] truncate sm:hidden">{firstName}</span>
        <span className="hidden max-w-[12rem] truncate sm:inline">{name}</span>
        <svg className={`h-4 w-4 shrink-0 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-50 mt-2 w-60 origin-top-right rounded-lg bg-white py-1 shadow-lg ring-1 ring-black/10">
          <div className="border-b border-gray-100 px-4 py-3">
            <p className="truncate text-sm font-semibold text-gray-900">{name}</p>
            {user?.email && <p className="truncate text-xs text-gray-500">{user.email}</p>}
          </div>
          <Link
            role="menuitem"
            to="/settings"
            className={`block px-4 py-2.5 text-sm ${
              settingsActive ? 'bg-odc-50 text-odc-800' : 'text-gray-700 hover:bg-gray-50'
            }`}
          >
            <span className={`flex items-center gap-2 ${settingsActive ? 'font-semibold' : 'font-medium'}`}>
              <Icon name="cog" />
              Settings
            </span>
            <span className="mt-0.5 block pl-[26px] text-xs font-normal text-gray-400">Pricing, catalog, and service keys</span>
          </Link>
          <div className="border-t border-gray-100">
            <button
              type="button"
              role="menuitem"
              onClick={handleLogout}
              className="flex w-full items-center px-4 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50"
            >
              Logout
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function StaffShell({ children }) {
  const { user, isAuthenticated } = useAuth()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1024px)')
    const onChange = () => {
      if (media.matches) setMobileOpen(false)
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    if (!mobileOpen) return undefined
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (event) => {
      if (event.key === 'Escape') setMobileOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previous
      document.removeEventListener('keydown', onKey)
    }
  }, [mobileOpen])

  if (!isAuthenticated) {
    return children
  }

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col bg-odc-900 lg:flex">
        <div className="flex h-16 shrink-0 items-center border-b border-r border-gray-200 bg-white px-4">
          <Link to="/" className="min-w-0">
            <Logo />
          </Link>
        </div>
        <SideNav pathname={location.pathname} />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-gray-900/50"
            onClick={() => setMobileOpen(false)}
          />
          <aside role="dialog" aria-modal="true" aria-label="Main menu" className="relative flex h-full w-[min(18rem,calc(100%-3rem))] flex-col bg-odc-900 shadow-xl">
            <div className="flex h-16 shrink-0 items-center justify-between gap-2 border-b border-gray-200 bg-white px-4">
              <Link to="/" onClick={() => setMobileOpen(false)} className="min-w-0">
                <Logo />
              </Link>
              <button
                type="button"
                aria-label="Close menu"
                onClick={() => setMobileOpen(false)}
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100"
              >
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true">
                  <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </div>
            <SideNav pathname={location.pathname} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-h-screen min-w-0 flex-col lg:pl-60">
        <header className="sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-gray-200 bg-white px-3 sm:px-6">
          <button
            type="button"
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-gray-600 hover:bg-gray-100 lg:hidden"
            aria-label="Open menu"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen(true)}
          >
            <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true">
              <path strokeLinecap="round" d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          <Link to="/" className="shrink-0 lg:hidden">
            <Logo className="h-8 max-w-[7.5rem] object-contain object-left" />
          </Link>
          <h1 className="hidden min-w-0 flex-1 truncate text-lg font-semibold text-gray-900 lg:block">
            {pageTitle(location.pathname)}
          </h1>
          <div className="ml-auto flex shrink-0 items-center gap-1 sm:gap-2">
            <Link
              to="/settings"
              title="Settings"
              aria-label="Settings"
              className={`inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md transition-colors ${
                isActive(location.pathname, '/settings')
                  ? 'bg-odc-50 text-odc-700'
                  : 'text-gray-500 hover:bg-gray-100 hover:text-gray-700'
              }`}
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </Link>
            <AccountMenu user={user} pathname={location.pathname} />
          </div>
        </header>
        <div className="min-w-0 flex-1 overflow-x-auto">
          {children}
        </div>
      </div>
    </div>
  )
}

export default StaffShell
