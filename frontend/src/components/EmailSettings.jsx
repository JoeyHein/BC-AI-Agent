import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useSearchParams } from 'react-router-dom'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function EmailSettings() {
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const [connections, setConnections] = useState([])
  const [loading, setLoading] = useState(true)
  const [connecting, setConnecting] = useState(false)
  const [successMessage, setSuccessMessage] = useState('')

  // Check if we just connected an email
  useEffect(() => {
    const emailConnected = searchParams.get('email_connected')
    if (emailConnected) {
      setSuccessMessage(`Successfully connected ${emailConnected}!`)
      setTimeout(() => setSuccessMessage(''), 5000)
    }
  }, [searchParams])

  // Load email connections
  useEffect(() => {
    loadConnections()
  }, [])

  const loadConnections = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/email-connections`)
      setConnections(response.data)
    } catch (error) {
      console.error('Failed to load email connections:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleConnectEmail = async () => {
    setConnecting(true)
    try {
      const response = await axios.get(`${API_URL}/api/email-connections/oauth/start`)
      const { authorization_url } = response.data

      // Redirect to Microsoft login
      window.location.href = authorization_url
    } catch (error) {
      console.error('Failed to start OAuth flow:', error)
      alert('Failed to start email connection. Please try again.')
      setConnecting(false)
    }
  }

  const handleDisconnect = async (connectionId) => {
    if (!confirm('Are you sure you want to disconnect this email?')) {
      return
    }

    try {
      await axios.delete(`${API_URL}/api/email-connections/${connectionId}`)
      // Reload connections
      loadConnections()
    } catch (error) {
      console.error('Failed to disconnect email:', error)
      alert('Failed to disconnect email. Please try again.')
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-gray-500">Loading...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="sm:flex sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Email Connections</h1>
          <p className="mt-2 text-sm text-gray-700">
            Connect your email accounts to monitor for quote requests
          </p>
        </div>
        <button
          onClick={handleConnectEmail}
          disabled={connecting}
          className="mt-4 sm:mt-0 inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
        >
          <svg className="mr-2 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          {connecting ? 'Connecting...' : 'Connect Email'}
        </button>
      </div>

      {successMessage && (
        <div className="rounded-md bg-green-50 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <p className="text-sm font-medium text-green-800">{successMessage}</p>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white shadow overflow-hidden sm:rounded-lg">
        {connections.length > 0 ? (
          <ul className="divide-y divide-gray-200">
            {connections.map((connection) => (
              <li key={connection.id} className="px-6 py-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center">
                      <div className="flex-shrink-0">
                        <svg className="h-10 w-10 text-indigo-600" fill="currentColor" viewBox="0 0 20 20">
                          <path d="M2.003 5.884L10 9.882l7.997-3.998A2 2 0 0016 4H4a2 2 0 00-1.997 1.884z" />
                          <path d="M18 8.118l-8 4-8-4V14a2 2 0 002 2h12a2 2 0 002-2V8.118z" />
                        </svg>
                      </div>
                      <div className="ml-4">
                        <p className="text-sm font-medium text-gray-900">{connection.email_address}</p>
                        <div className="flex items-center mt-1">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            connection.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                          }`}>
                            {connection.is_active ? 'Active' : 'Inactive'}
                          </span>
                          {connection.last_checked_at && (
                            <span className="ml-2 text-xs text-gray-500">
                              Last checked: {new Date(connection.last_checked_at).toLocaleString()}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="ml-4 flex-shrink-0">
                    <button
                      onClick={() => handleDisconnect(connection.id)}
                      className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
                    >
                      Disconnect
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-center py-12">
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">No email connections</h3>
            <p className="mt-1 text-sm text-gray-500">Get started by connecting your first email account.</p>
            <div className="mt-6">
              <button
                onClick={handleConnectEmail}
                type="button"
                className="inline-flex items-center px-4 py-2 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
              >
                <svg className="-ml-1 mr-2 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Connect Email
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="ml-3 flex-1">
            <h3 className="text-sm font-medium text-blue-800">How it works</h3>
            <div className="mt-2 text-sm text-blue-700">
              <ul className="list-disc list-inside space-y-1">
                <li>Click "Connect Email" to sign in with your Microsoft account</li>
                <li>We'll monitor your inbox every 15 minutes for quote requests</li>
                <li>AI automatically parses new quotes and adds them to the review queue</li>
                <li>You can disconnect an email at any time</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default EmailSettings
