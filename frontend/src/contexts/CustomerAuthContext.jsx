import { createContext, useContext, useState, useEffect } from 'react'
import axios from 'axios'

const CustomerAuthContext = createContext(null)

const API_URL = import.meta.env.VITE_API_URL || ''

// Create a separate axios instance for customer portal
const customerAxios = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json'
  }
})

export const CustomerAuthProvider = ({ children }) => {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState(localStorage.getItem('customerAuthToken'))

  // Set up axios interceptor for auth token
  useEffect(() => {
    if (token) {
      customerAxios.defaults.headers.common['Authorization'] = `Bearer ${token}`
    } else {
      delete customerAxios.defaults.headers.common['Authorization']
    }
  }, [token])

  // Load user on mount if token exists
  useEffect(() => {
    const loadUser = async () => {
      if (token) {
        try {
          const response = await customerAxios.get('/api/customer/me')
          setUser(response.data)
        } catch (error) {
          console.error('Failed to load customer user:', error)
          // Token is invalid, clear it
          logout()
        }
      }
      setLoading(false)
    }

    loadUser()
  }, [])

  const login = async (email, password) => {
    try {
      const response = await customerAxios.post('/api/customer/login', {
        email,
        password
      })

      const { access_token, user: userData } = response.data

      // Save token (separate from admin token)
      localStorage.setItem('customerAuthToken', access_token)
      setToken(access_token)
      setUser(userData)

      return { success: true }
    } catch (error) {
      console.error('Customer login error:', error)
      return {
        success: false,
        error: error.response?.data?.detail || 'Login failed'
      }
    }
  }

  const register = async (email, password, name, companyName = null, phone = null) => {
    try {
      await customerAxios.post('/api/customer/register', {
        email,
        password,
        name,
        company_name: companyName,
        phone
      })

      // After registration, log in
      return await login(email, password)
    } catch (error) {
      console.error('Customer registration error:', error)
      return {
        success: false,
        error: error.response?.data?.detail || 'Registration failed'
      }
    }
  }

  const forgotPassword = async (email) => {
    try {
      await customerAxios.post('/api/customer/forgot-password', { email })
      return { success: true }
    } catch (error) {
      console.error('Forgot password error:', error)
      return {
        success: false,
        error: error.response?.data?.detail || 'Failed to send reset email'
      }
    }
  }

  const resetPassword = async (token, newPassword) => {
    try {
      await customerAxios.post('/api/customer/reset-password', {
        token,
        new_password: newPassword
      })
      return { success: true }
    } catch (error) {
      console.error('Reset password error:', error)
      return {
        success: false,
        error: error.response?.data?.detail || 'Failed to reset password'
      }
    }
  }

  const updateProfile = async (name) => {
    try {
      const response = await customerAxios.patch('/api/customer/me', { name })
      setUser(response.data)
      return { success: true }
    } catch (error) {
      console.error('Update profile error:', error)
      return {
        success: false,
        error: error.response?.data?.detail || 'Failed to update profile'
      }
    }
  }

  const logout = () => {
    localStorage.removeItem('customerAuthToken')
    setToken(null)
    setUser(null)
  }

  const value = {
    user,
    loading,
    login,
    register,
    logout,
    forgotPassword,
    resetPassword,
    updateProfile,
    isAuthenticated: !!user,
    isBCLinked: !!user?.bc_customer_id,
    isEmailVerified: user?.email_verified ?? false
  }

  return (
    <CustomerAuthContext.Provider value={value}>
      {children}
    </CustomerAuthContext.Provider>
  )
}

export const useCustomerAuth = () => {
  const context = useContext(CustomerAuthContext)
  if (!context) {
    throw new Error('useCustomerAuth must be used within a CustomerAuthProvider')
  }
  return context
}

// Export the axios instance for use in API client
export { customerAxios }
