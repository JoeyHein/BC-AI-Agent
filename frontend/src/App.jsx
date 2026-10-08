import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
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
      <StaffShell>
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
          <Route path="/analytics/quoting" element={
            <ProtectedRoute requireReviewer>
              <QuotingAnalytics />
            </ProtectedRoute>
          } />
          <Route path="/analytics/order-age" element={
            <ProtectedRoute requireReviewer>
              <OrderAgeTracker />
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

          <Route path="/business" element={
            <ProtectedRoute>
              <BusinessDashboard />
            </ProtectedRoute>
          } />

          <Route path="/customers" element={
            <ProtectedRoute>
              <CustomerManagement />
            </ProtectedRoute>
          } />

          <Route path="/customers/:id" element={
            <ProtectedRoute>
              <CustomerDetail />
            </ProtectedRoute>
          } />

          <Route path="/orders" element={
            <ProtectedRoute>
              <OrderManagement />
            </ProtectedRoute>
          } />

          <Route path="/quotes" element={
            <ProtectedRoute>
              <QuoteSearch />
            </ProtectedRoute>
          } />

          <Route path="/leads" element={
            <ProtectedRoute>
              <QuoteLeads />
            </ProtectedRoute>
          } />

          <Route path="/install-referrals" element={
            <ProtectedRoute>
              <InstallReferralQueue />
            </ProtectedRoute>
          } />

          <Route path="/production" element={
            <ProtectedRoute>
              <ProductionCalendar />
            </ProtectedRoute>
          } />

          <Route path="/purchasing" element={
            <ProtectedRoute requireReviewer>
              <PurchasingDashboard />
            </ProtectedRoute>
          } />

          <Route path="/cut-work-orders" element={
            <ProtectedRoute requireReviewer>
              <CutWorkOrders />
            </ProtectedRoute>
          } />

          <Route path="/weekly-email" element={
            <ProtectedRoute requireAdmin>
              <WeeklyEmail />
            </ProtectedRoute>
          } />
        </Routes>
      </main>
      </StaffShell>

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
