import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

function ProtectedRoute({ children, requireAdmin = false, requireReviewer = false }) {
  const { user, loading } = useAuth()

  // Show loading state while checking auth
  if (loading) {
    return (
      <div className="flex justify-center items-center h-screen">
        <div className="text-gray-500">Loading...</div>
      </div>
    )
  }

  // Not authenticated - redirect to login
  if (!user) {
    return <Navigate to="/login" replace />
  }

  // Check role-based access
  if (requireAdmin && user.role !== 'admin') {
    return (
      <div className="flex justify-center items-center h-screen">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600">You need admin privileges to access this page.</p>
        </div>
      </div>
    )
  }

  if (requireReviewer && !['admin', 'reviewer'].includes(user.role)) {
    return (
      <div className="flex justify-center items-center h-screen">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600">You need reviewer privileges to access this page.</p>
        </div>
      </div>
    )
  }

  // Authenticated and authorized
  return children
}

export default ProtectedRoute
