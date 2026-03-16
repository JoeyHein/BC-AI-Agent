import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'

function CustomerLogin() {
  const [isLogin, setIsLogin] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [phone, setPhone] = useState('')
  const [accountType, setAccountType] = useState('dealer')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showForgotPassword, setShowForgotPassword] = useState(false)
  const [resetEmailSent, setResetEmailSent] = useState(false)
  const [registrationSubmitted, setRegistrationSubmitted] = useState(false)

  const { login, register, forgotPassword } = useCustomerAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      let result
      if (isLogin) {
        result = await login(email, password)
      } else {
        result = await register(email, password, name, companyName, phone, accountType)
      }

      if (result.success) {
        if (result.pending) {
          setRegistrationSubmitted(true)
        } else {
          navigate('/')
        }
      } else {
        setError(result.error)
      }
    } catch (err) {
      setError('An unexpected error occurred')
    } finally {
      setLoading(false)
    }
  }

  const handleForgotPassword = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const result = await forgotPassword(email)
      if (result.success) {
        setResetEmailSent(true)
      } else {
        setError(result.error)
      }
    } catch (err) {
      setError('An unexpected error occurred')
    } finally {
      setLoading(false)
    }
  }

  // Registration submitted / pending approval screen
  if (registrationSubmitted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-md w-full">
          <div className="bg-white shadow rounded-lg p-8 text-center">
            <div className="mx-auto flex items-center justify-center h-16 w-16 rounded-full bg-green-100 mb-6">
              <svg className="h-8 w-8 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Registration Submitted</h2>
            <p className="text-sm text-gray-600 mb-6">
              Your account is pending approval. We'll review your registration and send you an email once your account has been approved. This usually takes less than one business day.
            </p>
            <button
              onClick={() => {
                setRegistrationSubmitted(false)
                setIsLogin(true)
                setError('')
                setPassword('')
              }}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
            >
              Back to login
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (showForgotPassword) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-md w-full space-y-8">
          <div>
            <img src="/assets/opendc-logo.jpg" alt="OpenDC" className="h-16 mx-auto" />
            <h2 className="mt-6 text-center text-2xl font-bold text-gray-900">
              Reset your password
            </h2>
            <p className="mt-2 text-center text-sm text-gray-600">
              Enter your email and we'll send you a reset link
            </p>
          </div>

          {resetEmailSent ? (
            <div className="rounded-md bg-green-50 p-4">
              <p className="text-sm text-green-700">
                If an account exists with this email, you will receive a password reset link shortly.
              </p>
              <button
                onClick={() => {
                  setShowForgotPassword(false)
                  setResetEmailSent(false)
                }}
                className="mt-4 text-sm font-medium text-odc-600 hover:text-odc-500"
              >
                Back to login
              </button>
            </div>
          ) : (
            <form className="mt-8 space-y-6" onSubmit={handleForgotPassword}>
              {error && (
                <div className="rounded-md bg-red-50 p-4">
                  <p className="text-sm text-red-700">{error}</p>
                </div>
              )}

              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-700">
                  Email address
                </label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="mt-1 appearance-none relative block w-full px-3 py-2 border border-gray-300 rounded-md placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                  placeholder="you@example.com"
                />
              </div>

              <div>
                <button
                  type="submit"
                  disabled={loading}
                  className="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50"
                >
                  {loading ? 'Sending...' : 'Send reset link'}
                </button>
              </div>

              <div className="text-center">
                <button
                  type="button"
                  onClick={() => setShowForgotPassword(false)}
                  className="text-sm font-medium text-odc-600 hover:text-odc-500"
                >
                  Back to login
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div>
          <img src="/assets/opendc-logo.jpg" alt="OpenDC" className="h-16 mx-auto" />
          <h2 className="mt-6 text-center text-2xl font-bold text-gray-900">
            {isLogin ? 'Sign in to your account' : 'Create your account'}
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            {isLogin ? "Don't have an account? " : 'Already have an account? '}
            <button
              onClick={() => {
                setIsLogin(!isLogin)
                setError('')
              }}
              className="font-medium text-odc-600 hover:text-odc-500"
            >
              {isLogin ? 'Register here' : 'Sign in'}
            </button>
          </p>
        </div>

        <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
          {error && (
            <div className="rounded-md bg-red-50 p-4">
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          <div className="space-y-4">
            {!isLogin && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    I am a...
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <button
                      type="button"
                      onClick={() => setAccountType('dealer')}
                      className={`relative flex items-center justify-center px-4 py-3 border rounded-md text-sm font-medium transition-colors ${
                        accountType === 'dealer'
                          ? 'border-odc-500 bg-odc-50 text-odc-700 ring-2 ring-odc-500'
                          : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
                      }`}
                    >
                      Dealer / Installer
                    </button>
                    <button
                      type="button"
                      onClick={() => setAccountType('home_builder')}
                      className={`relative flex items-center justify-center px-4 py-3 border rounded-md text-sm font-medium transition-colors ${
                        accountType === 'home_builder'
                          ? 'border-odc-500 bg-odc-50 text-odc-700 ring-2 ring-odc-500'
                          : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
                      }`}
                    >
                      Home Builder
                    </button>
                  </div>
                </div>
                <div>
                  <label htmlFor="name" className="block text-sm font-medium text-gray-700">
                    Full Name
                  </label>
                  <input
                    id="name"
                    name="name"
                    type="text"
                    required={!isLogin}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="mt-1 appearance-none relative block w-full px-3 py-2 border border-gray-300 rounded-md placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                    placeholder="John Smith"
                  />
                </div>
                <div>
                  <label htmlFor="companyName" className="block text-sm font-medium text-gray-700">
                    Company Name
                  </label>
                  <input
                    id="companyName"
                    name="companyName"
                    type="text"
                    required={!isLogin}
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    className="mt-1 appearance-none relative block w-full px-3 py-2 border border-gray-300 rounded-md placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                    placeholder="Acme Doors Inc."
                  />
                </div>
                <div>
                  <label htmlFor="phone" className="block text-sm font-medium text-gray-700">
                    Phone <span className="text-gray-400 font-normal">(optional)</span>
                  </label>
                  <input
                    id="phone"
                    name="phone"
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className="mt-1 appearance-none relative block w-full px-3 py-2 border border-gray-300 rounded-md placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                    placeholder="(604) 555-1234"
                  />
                </div>
              </>
            )}

            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700">
                Email address
              </label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 appearance-none relative block w-full px-3 py-2 border border-gray-300 rounded-md placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete={isLogin ? 'current-password' : 'new-password'}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 appearance-none relative block w-full px-3 py-2 border border-gray-300 rounded-md placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                placeholder="********"
              />
            </div>
          </div>

          {isLogin && (
            <div className="flex items-center justify-end">
              <button
                type="button"
                onClick={() => setShowForgotPassword(true)}
                className="text-sm font-medium text-odc-600 hover:text-odc-500"
              >
                Forgot your password?
              </button>
            </div>
          )}

          <div>
            <button
              type="submit"
              disabled={loading}
              className="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50"
            >
              {loading ? (
                <span className="flex items-center">
                  <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  {isLogin ? 'Signing in...' : 'Creating account...'}
                </span>
              ) : (
                isLogin ? 'Sign in' : 'Create account'
              )}
            </button>
          </div>

          {!isLogin && (
            <p className="text-xs text-center text-gray-500">
              By registering, you agree to our Terms of Service and Privacy Policy.
              Your account will be reviewed and approved by our team.
            </p>
          )}
        </form>
      </div>
    </div>
  )
}

export default CustomerLogin
