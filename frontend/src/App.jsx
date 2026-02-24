import { BrowserRouter as Router, Routes, Route, Link, useNavigate, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './components/Login'
import Dashboard from './components/Dashboard'
import ReviewQueue from './components/ReviewQueue'
import QuoteDetail from './components/QuoteDetail'
import Analytics from './components/Analytics'
import EmailSettings from './components/EmailSettings'
import DoorConfigurator from './components/DoorConfigurator'
import CustomerManagement from './components/CustomerManagement'
import ProductionCalendar from './components/ProductionCalendar'
import OrderManagement from './components/OrderManagement'
import ChatBox from './components/Chat/ChatBox'
import SettingsPage from './components/Settings/SettingsPage'

function Navigation() {
  const { user, logout, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  if (!isAuthenticated) {
    return null
  }

  const isActive = (path) => {
    if (path === '/settings') return location.pathname.startsWith('/settings')
    return location.pathname === path
  }

  const navItems = [
    { path: '/', label: 'Dashboard' },
    { path: '/reviews', label: 'Reviews' },
    { path: '/analytics', label: 'Analytics' },
    { path: '/door-configurator', label: 'Configurator' },
    { path: '/customers', label: 'Customers' },
    { path: '/orders', label: 'Orders' },
    { path: '/production', label: 'Production' },
    { path: '/settings', label: 'Settings' },
  ]

  return (
    <nav className="bg-white shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-14">
          <div className="flex items-center">
            <Link to="/" className="flex-shrink-0">
              <img src="/assets/opendc-logo.jpg" alt="OpenDC" className="h-8" />
            </Link>
            <div className="hidden sm:flex sm:ml-8">
              {navItems.map((item) => (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`inline-flex items-center px-3 h-14 border-b-2 text-sm font-medium transition-colors ${
                    isActive(item.path)
                      ? 'border-odc-600 text-odc-700'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }`}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          </div>
          <div className="flex items-center space-x-3">
            <span className="text-sm text-gray-500">
              {user?.name || user?.email}
            </span>
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
  )
}

function AppContent() {
  const { isAuthenticated } = useAuth()

  // Handler for when chat actions are taken (refresh data as needed)
  const handleChatAction = (actions) => {
    // Actions like scheduling might need data refresh
    // Components using react-query will auto-refresh on focus
    // This handler can be extended for additional refresh logic
    console.log('Chat actions taken:', actions)
  }

  return (
    <div className="min-h-screen bg-gray-100">
      <Navigation />

      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <Routes>
          <Route path="/login" element={<Login />} />

          {/* Protected routes */}
          <Route path="/" element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          } />

          <Route path="/reviews" element={
            <ProtectedRoute>
              <ReviewQueue />
            </ProtectedRoute>
          } />

          <Route path="/reviews/:id" element={
            <ProtectedRoute requireReviewer>
              <QuoteDetail />
            </ProtectedRoute>
          } />

          <Route path="/analytics" element={
            <ProtectedRoute>
              <Analytics />
            </ProtectedRoute>
          } />

          <Route path="/door-configurator" element={
            <ProtectedRoute>
              <DoorConfigurator />
            </ProtectedRoute>
          } />

          <Route path="/settings" element={
            <ProtectedRoute>
              <SettingsPage />
            </ProtectedRoute>
          } />

          <Route path="/settings/email" element={
            <ProtectedRoute>
              <EmailSettings />
            </ProtectedRoute>
          } />

          <Route path="/customers" element={
            <ProtectedRoute>
              <CustomerManagement />
            </ProtectedRoute>
          } />

          <Route path="/orders" element={
            <ProtectedRoute>
              <OrderManagement />
            </ProtectedRoute>
          } />

          <Route path="/production" element={
            <ProtectedRoute>
              <ProductionCalendar />
            </ProtectedRoute>
          } />
        </Routes>
      </main>

      {/* Global AI Chat Box - only visible when authenticated */}
      {isAuthenticated && <ChatBox onAction={handleChatAction} />}
    </div>
  )
}

function App() {
  return (
    <Router>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </Router>
  )
}

export default App
