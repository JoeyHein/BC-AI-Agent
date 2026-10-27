import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

function PasswordForm({ title, intro, onSubmit, showName }) {
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    if (!token) {
      setError('This link is missing its token. Ask an owner to send a new one.')
      return
    }
    setLoading(true)
    try {
      const result = await onSubmit({ token, password, name })
      if (!result.success) setError(result.error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4">
      <div className="max-w-md w-full space-y-6">
        <div className="flex flex-col items-center">
          <img src="/assets/opendc-logo.jpg" alt="OpenDC" className="h-16 mb-4" />
          <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
          <p className="mt-2 text-center text-sm text-gray-600">{intro}</p>
        </div>
        <form className="space-y-4" onSubmit={handleSubmit}>
          {error && (
            <div className="rounded-md bg-red-50 p-4 text-sm text-red-800">{error}</div>
          )}
          {showName && (
            <label className="block text-sm font-medium text-gray-700">
              Your name
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
          )}
          <label className="block text-sm font-medium text-gray-700">
            Password
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </label>
          <p className="text-xs text-gray-500">At least 8 characters.</p>
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-odc-600 py-2 text-sm font-medium text-white hover:bg-odc-700 disabled:opacity-50"
          >
            {loading ? 'Saving...' : 'Save and sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}

export function SetupAccount() {
  const { completeSetup } = useAuth()
  const navigate = useNavigate()
  return (
    <PasswordForm
      title="Set up your login"
      intro="Choose a password for the OpenDC portal. This link is single-use."
      showName
      onSubmit={async (body) => {
        const result = await completeSetup(body)
        if (result.success) navigate('/')
        return result
      }}
    />
  )
}

export function ResetPassword() {
  const { completeReset } = useAuth()
  const navigate = useNavigate()
  return (
    <PasswordForm
      title="Choose a new password"
      intro="This reset link works for one hour."
      onSubmit={async (body) => {
        const result = await completeReset(body)
        if (result.success) navigate('/')
        return result
      }}
    />
  )
}
