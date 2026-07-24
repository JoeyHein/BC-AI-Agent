import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'
import { useCart } from '../../contexts/CartContext'
import { CUSTOMER_PARTS_FEATURES_ENABLED } from '../../config/featureFlags'

function CustomerLayout() {
  const { user, logout, isBCLinked, isDealer, isHomeBuilder } = useCustomerAuth()
  const { itemCount } = useCart()
  const navigate = useNavigate()
  const location = useLocation()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const isActive = (path) => {
    if (path === '' || path === '/') {
      return location.pathname === '/' || location.pathname === ''
    }
    return location.pathname.startsWith('/' + path)
  }

  const allNavItems = [
    { path: '', label: 'Dashboard', icon: HomeIcon },
    { path: 'saved-quotes', label: 'My Quotes', icon: DocumentIcon },
    { path: 'catalog', label: 'Catalog', icon: CatalogIcon, dealerOnly: true, wip: true },
    { path: 'spring-builder', label: 'Spring Builder', icon: SpringIcon, dealerOnly: true, wip: true },
    { path: 'cart', label: 'Cart', icon: ShoppingBagIcon, badge: true, dealerOnly: true, wip: true },
    { path: 'projects', label: 'Projects', icon: ProjectIcon, homeBuilderOnly: true },
    { path: 'orders', label: 'Orders', icon: ShoppingCartIcon },
    { path: 'account', label: 'Account', icon: UserIcon },
  ]

  const navItems = allNavItems.filter(item => {
    // Not-yet-released parts experience (Catalog / Spring Builder / Cart).
    if (item.wip && !CUSTOMER_PARTS_FEATURES_ENABLED) return false
    if (item.dealerOnly && !isDealer) return false
    if (item.homeBuilderOnly && !isHomeBuilder) return false
    return true
  })

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header + Navigation */}
      <nav className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14 gap-6">
            <div className="flex items-center gap-6 min-w-0">
              <Link to="/" className="flex-shrink-0 flex items-center">
                <img src="/assets/opendc-logo.jpg" alt="OpenDC" className="h-8 w-auto" />
              </Link>
              <div className="flex items-center">
                {navItems.map((item) => (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={`relative inline-flex items-center gap-1.5 px-3 h-14 border-b-2 text-sm font-medium whitespace-nowrap transition-colors ${
                      isActive(item.path)
                        ? 'border-odc-600 text-odc-700'
                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                    }`}
                  >
                    <item.icon className="h-4 w-4" />
                    {item.label}
                    {item.badge && itemCount > 0 && (
                      <span className="absolute top-2 -right-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold leading-none text-white bg-red-500 rounded-full">
                        {itemCount}
                      </span>
                    )}
                  </Link>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-3 flex-shrink-0">
              {!isBCLinked && (
                <span className="hidden md:inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800 whitespace-nowrap">
                  Not linked
                </span>
              )}
              {(() => {
                const primary = user?.bc_company_name || user?.name || user?.email
                const secondary = user?.bc_company_name && user?.name && user.name !== user.bc_company_name
                  ? user.name : null
                return (
                  <div className="hidden lg:flex flex-col items-end leading-tight max-w-[200px]">
                    <span className="text-sm font-medium text-gray-700 truncate w-full text-right">
                      {primary}
                    </span>
                    {secondary && (
                      <span className="text-xs text-gray-400 truncate w-full text-right">{secondary}</span>
                    )}
                  </div>
                )
              })()}
              <button
                onClick={handleLogout}
                className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm font-medium rounded-md text-gray-600 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 mt-auto">
        <div className="max-w-7xl mx-auto py-4 px-4 sm:px-6 lg:px-8">
          <p className="text-center text-sm text-gray-500">
            OpenDC Customer Portal - Need help? Contact support@opendc.ca
          </p>
        </div>
      </footer>
    </div>
  )
}

// Simple icon components
function HomeIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
    </svg>
  )
}

function DocumentIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
    </svg>
  )
}

function ShoppingBagIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z" />
    </svg>
  )
}

function ShoppingCartIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z" />
    </svg>
  )
}

function UserIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
    </svg>
  )
}

function CatalogIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
    </svg>
  )
}

function ProjectIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
    </svg>
  )
}

function SpringIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
}

export default CustomerLayout
