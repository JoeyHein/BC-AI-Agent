import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { customerAuthApi } from '../../api/customerClient'

function EmailVerification() {
  const { token } = useParams()
  const [status, setStatus] = useState('verifying') // verifying, success, error
  const [message, setMessage] = useState('')

  useEffect(() => {
    const verifyEmail = async () => {
      try {
        const response = await customerAuthApi.verifyEmail(token)
        setStatus('success')
        setMessage(response.data.message || 'Your email has been verified successfully!')
      } catch (error) {
        setStatus('error')
        setMessage(error.response?.data?.detail || 'Failed to verify email. The link may be expired or invalid.')
      }
    }

    if (token) {
      verifyEmail()
    }
  }, [token])

  return (
    <div className="min-h-screen bg-gray-100 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <h1 className="text-center text-3xl font-bold text-odc-600">OPENDC</h1>
        <p className="mt-1 text-center text-sm text-gray-500">Customer Portal</p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <div className="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
          {status === 'verifying' && (
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600 mx-auto"></div>
              <p className="mt-4 text-gray-600">Verifying your email address...</p>
            </div>
          )}

          {status === 'success' && (
            <div className="text-center">
              <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100">
                <CheckIcon className="h-6 w-6 text-green-600" />
              </div>
              <h2 className="mt-4 text-lg font-medium text-gray-900">Email Verified!</h2>
              <p className="mt-2 text-sm text-gray-500">{message}</p>
              <Link
                to="/login"
                className="mt-6 inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700"
              >
                Sign In to Your Account
              </Link>
            </div>
          )}

          {status === 'error' && (
            <div className="text-center">
              <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-red-100">
                <XIcon className="h-6 w-6 text-red-600" />
              </div>
              <h2 className="mt-4 text-lg font-medium text-gray-900">Verification Failed</h2>
              <p className="mt-2 text-sm text-gray-500">{message}</p>
              <div className="mt-6 space-y-3">
                <Link
                  to="/login"
                  className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700"
                >
                  Go to Login
                </Link>
                <p className="text-sm text-gray-500">
                  Need help?{' '}
                  <a href="mailto:support@opendc.com" className="text-odc-600 hover:text-odc-500">
                    Contact Support
                  </a>
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function CheckIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  )
}

function XIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}

export default EmailVerification
