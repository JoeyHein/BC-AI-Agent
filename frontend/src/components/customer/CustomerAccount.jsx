import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'
import { customerAuthApi } from '../../api/customerClient'

function CustomerAccount() {
  const { user, updateProfile, isBCLinked, isEmailVerified } = useCustomerAuth()
  const [name, setName] = useState(user?.name || '')
  const [editingName, setEditingName] = useState(false)
  const [showPasswordForm, setShowPasswordForm] = useState(false)
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [message, setMessage] = useState({ type: '', text: '' })

  const handleUpdateName = async () => {
    if (!name.trim()) {
      setMessage({ type: 'error', text: 'Name cannot be empty' })
      return
    }

    const result = await updateProfile(name.trim())
    if (result.success) {
      setMessage({ type: 'success', text: 'Name updated successfully' })
      setEditingName(false)
    } else {
      setMessage({ type: 'error', text: result.error })
    }
  }

  const passwordMutation = useMutation({
    mutationFn: async () => {
      return customerAuthApi.changePassword(oldPassword, newPassword)
    },
    onSuccess: () => {
      setMessage({ type: 'success', text: 'Password changed successfully' })
      setShowPasswordForm(false)
      setOldPassword('')
      setNewPassword('')
      setConfirmPassword('')
    },
    onError: (error) => {
      setMessage({ type: 'error', text: error.response?.data?.detail || 'Failed to change password' })
    }
  })

  const handleChangePassword = async (e) => {
    e.preventDefault()
    setMessage({ type: '', text: '' })

    if (newPassword !== confirmPassword) {
      setMessage({ type: 'error', text: 'New passwords do not match' })
      return
    }

    if (newPassword.length < 8) {
      setMessage({ type: 'error', text: 'Password must be at least 8 characters' })
      return
    }

    passwordMutation.mutate()
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Account Settings</h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage your account information and preferences
        </p>
      </div>

      {/* Message */}
      {message.text && (
        <div className={`p-4 rounded-md ${
          message.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
        }`}>
          {message.text}
        </div>
      )}

      {/* Profile section */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-medium text-gray-900">Profile Information</h2>
        </div>
        <div className="px-6 py-4 space-y-4">
          {/* Email */}
          <div className="flex items-center justify-between py-3">
            <div>
              <p className="text-sm font-medium text-gray-500">Email</p>
              <p className="mt-1 text-sm text-gray-900">{user?.email}</p>
            </div>
            <div className="flex items-center space-x-2">
              {isEmailVerified ? (
                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                  Verified
                </span>
              ) : (
                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
                  Not Verified
                </span>
              )}
            </div>
          </div>

          {/* Name */}
          <div className="flex items-center justify-between py-3 border-t border-gray-200">
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-500">Name</p>
              {editingName ? (
                <div className="mt-1 flex items-center space-x-2">
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="block w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                  />
                  <button
                    onClick={handleUpdateName}
                    className="inline-flex items-center px-3 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => {
                      setEditingName(false)
                      setName(user?.name || '')
                    }}
                    className="inline-flex items-center px-3 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <p className="mt-1 text-sm text-gray-900">{user?.name || 'Not set'}</p>
              )}
            </div>
            {!editingName && (
              <button
                onClick={() => setEditingName(true)}
                className="text-sm text-odc-600 hover:text-odc-500"
              >
                Edit
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Business Central Link */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-medium text-gray-900">Business Account</h2>
        </div>
        <div className="px-6 py-4">
          {isBCLinked ? (
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-500">Company</p>
                <p className="mt-1 text-sm text-gray-900">{user?.bc_company_name || 'Linked'}</p>
                <p className="text-xs text-gray-500 mt-1">Customer ID: {user?.bc_customer_id}</p>
              </div>
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                Linked
              </span>
            </div>
          ) : (
            <div className="text-center py-4">
              <p className="text-sm text-gray-500">
                Your account is not yet linked to a business account.
              </p>
              <p className="mt-2 text-sm text-gray-500">
                Contact support to link your account and access all features.
              </p>
              <a
                href="mailto:support@opendc.com?subject=Link%20My%20Account"
                className="mt-4 inline-flex items-center px-4 py-2 border border-odc-600 text-sm font-medium rounded-md text-odc-600 hover:bg-blue-50"
              >
                Contact Support
              </a>
            </div>
          )}
        </div>
      </div>

      {/* Password section */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-medium text-gray-900">Security</h2>
        </div>
        <div className="px-6 py-4">
          {showPasswordForm ? (
            <form onSubmit={handleChangePassword} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Current Password
                </label>
                <input
                  type="password"
                  value={oldPassword}
                  onChange={(e) => setOldPassword(e.target.value)}
                  required
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  New Password
                </label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={8}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Confirm New Password
                </label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                />
              </div>
              <div className="flex items-center space-x-3">
                <button
                  type="submit"
                  disabled={passwordMutation.isLoading}
                  className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
                >
                  {passwordMutation.isLoading ? 'Changing...' : 'Change Password'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowPasswordForm(false)
                    setOldPassword('')
                    setNewPassword('')
                    setConfirmPassword('')
                  }}
                  className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-500">Password</p>
                <p className="mt-1 text-sm text-gray-900">********</p>
              </div>
              <button
                onClick={() => setShowPasswordForm(true)}
                className="text-sm text-odc-600 hover:text-odc-500"
              >
                Change Password
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Account info */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-medium text-gray-900">Account Information</h2>
        </div>
        <div className="px-6 py-4">
          <dl className="space-y-4">
            <div className="flex justify-between">
              <dt className="text-sm text-gray-500">Account Created</dt>
              <dd className="text-sm text-gray-900">
                {user?.created_at
                  ? new Date(user.created_at).toLocaleDateString('en-US', {
                      year: 'numeric',
                      month: 'long',
                      day: 'numeric'
                    })
                  : 'Unknown'}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-sm text-gray-500">Last Login</dt>
              <dd className="text-sm text-gray-900">
                {user?.last_login_at
                  ? new Date(user.last_login_at).toLocaleDateString('en-US', {
                      year: 'numeric',
                      month: 'long',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit'
                    })
                  : 'Unknown'}
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  )
}

export default CustomerAccount
