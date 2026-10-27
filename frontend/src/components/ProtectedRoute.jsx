import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

function ProtectedRoute({ children, permission, anyOf }) {
  const { user, loading, can, canAny } = useAuth()

  if (loading) {
    return (
      <div className="flex justify-center items-center h-screen">
        <div className="text-gray-500">Loading...</div>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  const allowed = permission ? can(permission) : anyOf ? canAny(anyOf) : true
  if (!allowed) {
    return (
      <div className="flex justify-center items-center h-screen">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600">Your login does not include this page.</p>
        </div>
      </div>
    )
  }

  return children
}

export default ProtectedRoute
