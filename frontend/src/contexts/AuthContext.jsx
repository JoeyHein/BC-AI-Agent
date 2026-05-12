import { createContext, useContext, useState, useEffect } from 'react'
import axios from 'axios'
import { useQueryClient } from '@tanstack/react-query'

const AuthContext = createContext(null)

const API_URL = import.meta.env.VITE_API_URL || ''

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState(localStorage.getItem('authToken'))
  // Cleared on every login + logout so a different admin/reviewer
  // logging into the same browser can never see the previous user's
  // cached responses.
  const queryClient = useQueryClient()

  // Set up axios interceptor for auth token
  useEffect(() => {
    if (token) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`
    } else {
      delete axios.defaults.headers.common['Authorization']
    }
  }, [token])

  // Load user on mount if token exists
  useEffect(() => {
    const loadUser = async () => {
      if (token) {
        try {
          const response = await axios.get(`${API_URL}/api/auth/me`)
          setUser(response.data)
        } catch (error) {
          console.error('Failed to load user:', error)
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
      // Wipe any cached responses from a prior session before we set
      // the new user, so a different admin logging into the same
      // browser doesn't see stale data on first render.
      queryClient.clear()

      const response = await axios.post(`${API_URL}/api/auth/login`, {
        email,
        password
      })

      const { access_token, user: userData } = response.data

      // Save token
      localStorage.setItem('authToken', access_token)
      setToken(access_token)
      setUser(userData)

      return { success: true }
    } catch (error) {
      console.error('Login error:', error)
      return {
        success: false,
        error: error.response?.data?.detail || 'Login failed'
      }
    }
  }

  const register = async (email, password, name) => {
    try {
      const response = await axios.post(`${API_URL}/api/auth/register`, {
        email,
        password,
        name,
        role: 'viewer'  // Default role for self-registration
      })

      // After registration, log in
      return await login(email, password)
    } catch (error) {
      console.error('Registration error:', error)
      return {
        success: false,
        error: error.response?.data?.detail || 'Registration failed'
      }
    }
  }

  const logout = () => {
    localStorage.removeItem('authToken')
    setToken(null)
    setUser(null)
    // Clear all cached query data so the next user (or anonymous state)
    // can never see the previous user's responses.
    queryClient.clear()
  }

  const value = {
    user,
    loading,
    login,
    register,
    logout,
    isAuthenticated: !!user,
    isAdmin: user?.role === 'admin',
    isReviewer: user?.role === 'reviewer' || user?.role === 'admin'
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
