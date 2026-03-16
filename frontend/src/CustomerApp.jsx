import { HashRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CustomerAuthProvider, useCustomerAuth } from './contexts/CustomerAuthContext'

// Customer Portal Components
import CustomerLayout from './components/customer/CustomerLayout'
import CustomerLogin from './components/customer/CustomerLogin'
import CustomerDashboard from './components/customer/CustomerDashboard'
import SavedQuotes from './components/customer/SavedQuotes'
import QuoteBuilder from './components/customer/QuoteBuilder'
import MyOrders from './components/customer/MyOrders'
import OrderDetail from './components/customer/OrderDetail'
import OrderTracking from './components/customer/OrderTracking'
import CustomerAccount from './components/customer/CustomerAccount'
import EmailVerification from './components/customer/EmailVerification'
import ResetPassword from './components/customer/ResetPassword'
import NotFound from './components/customer/NotFound'
import ErrorBoundary from './components/customer/ErrorBoundary'
import PartsCatalog from './components/customer/PartsCatalog'
import SpringBuilder from './components/customer/SpringBuilder'
import SpecialOrders from './components/customer/SpecialOrders'
import PartsCart from './components/customer/PartsCart'
import ProjectManager from './components/customer/ProjectManager'
import { CartProvider } from './contexts/CartContext'

// Create React Query client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      refetchOnWindowFocus: false,
    },
  },
})

// Protected route component for customer portal
function CustomerProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useCustomerAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return children
}

// 404 route - show not found for authenticated users, redirect to login for unauthenticated
function NotFoundRoute() {
  const { isAuthenticated, loading } = useCustomerAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <NotFound />
}

// Account-type gated route — redirects to dashboard if account type is not allowed
function AccountGatedRoute({ allowed, children }) {
  const { accountType, loading } = useCustomerAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  if (!allowed.includes(accountType)) {
    return <Navigate to="/" replace />
  }

  return children
}

// Public route - redirect to dashboard if already authenticated
function CustomerPublicRoute({ children }) {
  const { isAuthenticated, loading } = useCustomerAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  return children
}

function CustomerAppContent() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={
        <CustomerPublicRoute>
          <CustomerLogin />
        </CustomerPublicRoute>
      } />
      <Route path="/verify-email/:token" element={<EmailVerification />} />
      <Route path="/reset-password/:token" element={<ResetPassword />} />

      {/* Protected routes with layout */}
      <Route element={
        <CustomerProtectedRoute>
          <CustomerLayout />
        </CustomerProtectedRoute>
      }>
        <Route index element={<CustomerDashboard />} />
        <Route path="saved-quotes" element={<SavedQuotes />} />
        <Route path="saved-quotes/new" element={<QuoteBuilder />} />
        <Route path="saved-quotes/:id" element={<QuoteBuilder />} />
        <Route path="catalog" element={<AccountGatedRoute allowed={['dealer']}><PartsCatalog /></AccountGatedRoute>} />
        <Route path="spring-builder" element={<AccountGatedRoute allowed={['dealer']}><SpringBuilder /></AccountGatedRoute>} />
        <Route path="cart" element={<AccountGatedRoute allowed={['dealer']}><PartsCart /></AccountGatedRoute>} />
        <Route path="special-orders" element={<AccountGatedRoute allowed={['dealer']}><SpecialOrders /></AccountGatedRoute>} />
        <Route path="projects" element={<AccountGatedRoute allowed={['home_builder']}><ProjectManager /></AccountGatedRoute>} />
        <Route path="projects/:id" element={<AccountGatedRoute allowed={['home_builder']}><ProjectManager /></AccountGatedRoute>} />
        <Route path="orders" element={<MyOrders />} />
        <Route path="orders/:id" element={<OrderDetail />} />
        <Route path="orders/:id/tracking" element={<OrderTracking />} />
        <Route path="account" element={<CustomerAccount />} />
      </Route>

      {/* Catch all - show 404 for authenticated, redirect to login for unauthenticated */}
      <Route path="*" element={<NotFoundRoute />} />
    </Routes>
  )
}

function CustomerApp() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <Router>
          <CustomerAuthProvider>
            <CartProvider>
              <CustomerAppContent />
            </CartProvider>
          </CustomerAuthProvider>
        </Router>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

export default CustomerApp
