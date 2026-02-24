import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useSearchParams } from 'react-router-dom'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function EmailSettings() {
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const [connections, setConnections] = useState([])
  const [monitoringStatus, setMonitoringStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [connecting, setConnecting] = useState(false)
  const [checkingAll, setCheckingAll] = useState(false)
  const [checkingId, setCheckingId] = useState(null)
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
      const [connectionsRes, statusRes] = await Promise.all([
        axios.get(`${API_URL}/api/email-connections`),
        axios.get(`${API_URL}/api/email-connections/monitoring/status`)
      ])
      setConnections(connectionsRes.data)
      setMonitoringStatus(statusRes.data)
    } catch (error) {
      console.error('Failed to load email connections:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleCheckAllEmails = async () => {
    setCheckingAll(true)
    try {
      const response = await axios.post(`${API_URL}/api/email-connections/monitoring/check-now`)
      setSuccessMessage(`Email check complete! Found ${response.data.results.new_emails_found} new emails, parsed ${response.data.results.quote_requests_parsed} quote requests.`)
      setTimeout(() => setSuccessMessage(''), 8000)
      // Reload to get updated status
      loadConnections()
    } catch (error) {
      console.error('Failed to check emails:', error)
      alert('Failed to check emails. Please try again.')
    } finally {
      setCheckingAll(false)
    }
  }

  const handleCheckSingleInbox = async (connectionId) => {
    setCheckingId(connectionId)
    try {
      const response = await axios.post(`${API_URL}/api/email-connections/${connectionId}/check-now`)
      setSuccessMessage(`Checked ${response.data.email_address}: Found ${response.data.results.new_emails} new emails.`)
      setTimeout(() => setSuccessMessage(''), 5000)
      // Reload to get updated status
      loadConnections()
    } catch (error) {
      console.error('Failed to check inbox:', error)
      alert('Failed to check inbox. Please try again.')
    } finally {
      setCheckingId(null)
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
        <div className="mt-4 sm:mt-0 flex space-x-3">
          <button
            onClick={handleCheckAllEmails}
            disabled={checkingAll || connections.length === 0}
            className="inline-flex items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50"
          >
            <svg className={`mr-2 h-5 w-5 ${checkingAll ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {checkingAll ? 'Checking...' : 'Check All Now'}
          </button>
          <button
            onClick={handleConnectEmail}
            disabled={connecting}
            className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50"
          >
            <svg className="mr-2 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            {connecting ? 'Connecting...' : 'Connect Email'}
          </button>
        </div>
      </div>

      {/* Monitoring Status Panel */}
      {monitoringStatus && (
        <div className={`rounded-lg p-4 ${
          monitoringStatus.health === 'healthy' ? 'bg-green-50 border border-green-200' :
          monitoringStatus.health === 'warning' ? 'bg-yellow-50 border border-yellow-200' :
          'bg-red-50 border border-red-200'
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center">
              <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${
                monitoringStatus.health === 'healthy' ? 'bg-green-100 text-green-800' :
                monitoringStatus.health === 'warning' ? 'bg-yellow-100 text-yellow-800' :
                'bg-red-100 text-red-800'
              }`}>
                {monitoringStatus.health === 'healthy' ? 'All Systems Healthy' :
                 monitoringStatus.health === 'warning' ? 'Warnings Detected' :
                 'Critical Issues'}
              </span>
              <span className="ml-4 text-sm text-gray-600">
                {monitoringStatus.total_accounts} account{monitoringStatus.total_accounts !== 1 ? 's' : ''} monitored
              </span>
            </div>
          </div>
          {monitoringStatus.warnings && monitoringStatus.warnings.length > 0 && (
            <ul className="mt-3 text-sm text-gray-600 space-y-1">
              {monitoringStatus.warnings.map((warning, idx) => (
                <li key={idx} className="flex items-center">
                  <svg className="h-4 w-4 text-yellow-500 mr-2" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  {warning}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

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
                        <svg className="h-10 w-10 text-odc-600" fill="currentColor" viewBox="0 0 20 20">
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
                  <div className="ml-4 flex-shrink-0 flex space-x-2">
                    <button
                      onClick={() => handleCheckSingleInbox(connection.id)}
                      disabled={checkingId === connection.id}
                      className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50"
                    >
                      <svg className={`mr-1 h-4 w-4 ${checkingId === connection.id ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                      {checkingId === connection.id ? 'Checking...' : 'Check'}
                    </button>
                    <button
                      onClick={() => handleDisconnect(connection.id)}
                      className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
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
                className="inline-flex items-center px-4 py-2 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
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
