import { BrowserRouter as Router, Navigate, Routes, Route } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import StaffShell from './components/StaffShell'
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
import InstallReferralQueue from './components/InstallReferralQueue'
import WeeklyEmail from './components/WeeklyEmail'
import BusinessDashboard from './components/BusinessDashboard'
import CustomerDetail from './components/CustomerDetail'
import QuoteLeads from './components/QuoteLeads'
import QuoteSearch from './components/QuoteSearch'
import QuotingAnalytics from './pages/QuotingAnalytics'
import OrderAgeTracker from './pages/OrderAgeTracker'
import PurchasingDashboard from './components/Purchasing/PurchasingDashboard'
import CutWorkOrders from './components/Purchasing/CutWorkOrders'
import { ResetPassword, SetupAccount } from './components/SetupAccount'
import { showChat, showDashboard } from './utils/access'

function HomeGate() {
  const { user, loading, can } = useAuth()
  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-gray-500">Loading...</div>
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  if (showDashboard(user)) return <Dashboard />
  if (can('configurator.use') || can('quotes.edit')) return <Navigate to="/door-configurator" replace />
  return (
    <div className="bg-white shadow rounded-lg p-6">
      <h1 className="text-xl font-semibold text-gray-900">Welcome</h1>
      <p className="mt-2 text-sm text-gray-600">Your login does not include the dashboard. Use the menu for the pages you can open.</p>
    </div>
  )
}

function AppContent() {
  const { user, isAuthenticated } = useAuth()

  // Handler for when chat actions are taken (refresh data as needed)
  const handleChatAction = (actions) => {
    // Actions like scheduling might need data refresh
    // Components using react-query will auto-refresh on focus
    // This handler can be extended for additional refresh logic
    console.log('Chat actions taken:', actions)
  }

  return (
    <div className="min-h-screen bg-gray-100">
      <StaffShell>
      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/setup" element={<SetupAccount />} />
          <Route path="/reset-password" element={<ResetPassword />} />

          {/* Protected routes */}
          <Route path="/" element={<HomeGate />} />

          <Route path="/reviews" element={
            <ProtectedRoute permission="quotes.view">
              <ReviewQueue />
            </ProtectedRoute>
          } />

          <Route path="/reviews/:id" element={
            <ProtectedRoute permission="quotes.edit">
              <QuoteDetail />
            </ProtectedRoute>
          } />

          <Route path="/analytics" element={
            <ProtectedRoute anyOf={['quotes.view', 'sales_orders.view']}>
              <Analytics />
            </ProtectedRoute>
          } />
          <Route path="/analytics/quoting" element={
            <ProtectedRoute permission="quotes.view">
              <QuotingAnalytics />
            </ProtectedRoute>
          } />
          <Route path="/analytics/order-age" element={
            <ProtectedRoute permission="sales_orders.view">
              <OrderAgeTracker />
            </ProtectedRoute>
          } />

          <Route path="/door-configurator" element={
            <ProtectedRoute anyOf={['configurator.use', 'quotes.edit']}>
              <DoorConfigurator />
            </ProtectedRoute>
          } />

          <Route path="/settings" element={
            <ProtectedRoute anyOf={['settings.view', 'pricing.edit', 'users.view', 'inventory.view', 'purchase_orders.view']}>
              <SettingsPage />
            </ProtectedRoute>
          } />

          <Route path="/settings/email" element={
            <ProtectedRoute permission="settings.view">
              <EmailSettings />
            </ProtectedRoute>
          } />

          <Route path="/business" element={
            <ProtectedRoute anyOf={['users.manage', 'quotes.edit', 'sales_orders.edit', 'purchase_orders.view', 'sales_orders.view']}>
              <BusinessDashboard />
            </ProtectedRoute>
          } />

          <Route path="/customers" element={
            <ProtectedRoute permission="customers.view">
              <CustomerManagement />
            </ProtectedRoute>
          } />

          <Route path="/customers/:id" element={
            <ProtectedRoute permission="customers.view">
              <CustomerDetail />
            </ProtectedRoute>
          } />

          <Route path="/orders" element={
            <ProtectedRoute permission="sales_orders.view">
              <OrderManagement />
            </ProtectedRoute>
          } />

          <Route path="/quotes" element={
            <ProtectedRoute permission="quotes.view">
              <QuoteSearch />
            </ProtectedRoute>
          } />

          <Route path="/leads" element={
            <ProtectedRoute permission="quotes.view">
              <QuoteLeads />
            </ProtectedRoute>
          } />

          <Route path="/install-referrals" element={
            <ProtectedRoute permission="customers.view">
              <InstallReferralQueue />
            </ProtectedRoute>
          } />

          <Route path="/production" element={
            <ProtectedRoute permission="production.view">
              <ProductionCalendar />
            </ProtectedRoute>
          } />

          <Route path="/purchasing" element={
            <ProtectedRoute permission="purchase_orders.view">
              <PurchasingDashboard />
            </ProtectedRoute>
          } />

          <Route path="/cut-work-orders" element={
            <ProtectedRoute permission="production.view">
              <CutWorkOrders />
            </ProtectedRoute>
          } />

          <Route path="/weekly-email" element={
            <ProtectedRoute permission="users.manage">
              <WeeklyEmail />
            </ProtectedRoute>
          } />
        </Routes>
      </main>
      </StaffShell>

      {/* Global AI Chat Box - only visible when authenticated */}
      {isAuthenticated && showChat(user) && <ChatBox onAction={handleChatAction} />}
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
