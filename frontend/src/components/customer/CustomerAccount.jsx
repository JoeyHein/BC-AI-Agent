import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'
import { customerAuthApi, customerTeamApi } from '../../api/customerClient'
import { formatDate } from '../../utils/datetime'

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

      {/* Team management — visible to all team members, but only the
          customer admin can add/edit/remove. */}
      <TeamPanel currentUser={user} />

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
                  disabled={passwordMutation.isPending}
                  className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
                >
                  {passwordMutation.isPending ? 'Changing...' : 'Change Password'}
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
                  ? formatDate(user.created_at, 'en-US', {
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
                  ? formatDate(user.last_login_at, 'en-US', {
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

function TeamPanel({ currentUser }) {
  const queryClient = useQueryClient()
  const [showAddForm, setShowAddForm] = useState(false)
  const [newEmail, setNewEmail] = useState('')
  const [newName, setNewName] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newAdmin, setNewAdmin] = useState(false)
  const [feedback, setFeedback] = useState({ type: '', text: '' })

  const isAdmin = !!currentUser?.is_customer_admin
  const isBCLinked = !!currentUser?.bc_customer_id

  const { data: members = [], isLoading, error } = useQuery({
    queryKey: ['customer-team'],
    queryFn: async () => {
      const r = await customerTeamApi.list()
      return r.data
    },
    enabled: isBCLinked,
    retry: 1,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['customer-team'] })

  const addMutation = useMutation({
    mutationFn: () => customerTeamApi.add({
      email: newEmail.trim(),
      name: newName.trim() || undefined,
      password: newPassword,
      is_customer_admin: newAdmin,
    }),
    onSuccess: () => {
      setFeedback({ type: 'success', text: 'Team member added.' })
      setNewEmail(''); setNewName(''); setNewPassword(''); setNewAdmin(false)
      setShowAddForm(false)
      invalidate()
    },
    onError: (err) => {
      setFeedback({ type: 'error', text: err.response?.data?.detail || 'Failed to add team member.' })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ userId, patch }) => customerTeamApi.update(userId, patch),
    onSuccess: () => { setFeedback({ type: 'success', text: 'Updated.' }); invalidate() },
    onError: (err) => setFeedback({
      type: 'error',
      text: err.response?.data?.detail || 'Failed to update team member.',
    }),
  })

  const removeMutation = useMutation({
    mutationFn: (userId) => customerTeamApi.remove(userId),
    onSuccess: () => { setFeedback({ type: 'success', text: 'Team member removed.' }); invalidate() },
    onError: (err) => setFeedback({
      type: 'error',
      text: err.response?.data?.detail || 'Failed to remove team member.',
    }),
  })

  if (!isBCLinked) {
    return null  // No team management until BC link exists
  }

  const handleAdd = (e) => {
    e.preventDefault()
    setFeedback({ type: '', text: '' })
    if (!newEmail.trim()) {
      setFeedback({ type: 'error', text: 'Email is required.' })
      return
    }
    if (newPassword && newPassword.length < 8) {
      setFeedback({ type: 'error', text: 'Password must be at least 8 characters.' })
      return
    }
    addMutation.mutate()
  }

  return (
    <div className="bg-white shadow rounded-lg">
      <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Team Members</h2>
          <p className="mt-0.5 text-xs text-gray-500">
            {isAdmin
              ? 'Add or remove staff who can access your account.'
              : 'Read-only — only an admin can change team members. Contact your account admin to make changes.'}
          </p>
        </div>
        {isAdmin && !showAddForm && (
          <button
            onClick={() => { setShowAddForm(true); setFeedback({ type: '', text: '' }) }}
            className="inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700"
          >
            + Add User
          </button>
        )}
      </div>

      {feedback.text && (
        <div className={`mx-6 mt-4 p-3 rounded text-sm ${
          feedback.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
        }`}>
          {feedback.text}
        </div>
      )}

      {showAddForm && (
        <form onSubmit={handleAdd} className="px-6 py-4 border-b border-gray-200 bg-gray-50 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Email *</label>
              <input
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                required
                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Name</label>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Password
                <span className="text-gray-400 ml-1">(required only for new users)</span>
              </label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                minLength={8}
                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 text-sm"
              />
            </div>
            <div className="flex items-end">
              <label className="inline-flex items-center text-sm">
                <input
                  type="checkbox"
                  checked={newAdmin}
                  onChange={(e) => setNewAdmin(e.target.checked)}
                  className="rounded border-gray-300 text-odc-600 focus:ring-odc-500"
                />
                <span className="ml-2">Make this person a customer admin</span>
              </label>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <button
              type="submit"
              disabled={addMutation.isPending}
              className="inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
            >
              {addMutation.isPending ? 'Adding...' : 'Add Member'}
            </button>
            <button
              type="button"
              onClick={() => { setShowAddForm(false); setFeedback({ type: '', text: '' }) }}
              className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="overflow-x-auto">
        {isLoading ? (
          <div className="px-6 py-6 text-sm text-gray-500">Loading team...</div>
        ) : error ? (
          <div className="px-6 py-6 text-sm text-red-600">
            Couldn't load team: {error.response?.data?.detail || error.message}
          </div>
        ) : members.length === 0 ? (
          <div className="px-6 py-6 text-sm text-gray-500">No team members yet.</div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Member</th>
                <th className="px-6 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Role</th>
                <th className="px-6 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Status</th>
                <th className="px-6 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Last Login</th>
                {isAdmin && <th className="px-6 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Actions</th>}
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-100">
              {members.map(m => (
                <tr key={m.id} className={m.is_self ? 'bg-blue-50/40' : ''}>
                  <td className="px-6 py-3">
                    <div className="text-sm font-medium text-gray-900">
                      {m.name || m.email}
                      {m.is_self && <span className="ml-2 text-xs text-blue-700">(you)</span>}
                    </div>
                    <div className="text-xs text-gray-500">{m.email}</div>
                  </td>
                  <td className="px-6 py-3">
                    {m.is_customer_admin ? (
                      <span className="inline-block px-2 py-0.5 text-xs font-medium rounded bg-odc-100 text-odc-700">Admin</span>
                    ) : (
                      <span className="inline-block px-2 py-0.5 text-xs font-medium rounded bg-gray-100 text-gray-700">Member</span>
                    )}
                  </td>
                  <td className="px-6 py-3">
                    {m.is_active ? (
                      <span className="inline-block px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-700">Active</span>
                    ) : (
                      <span className="inline-block px-2 py-0.5 text-xs font-medium rounded bg-yellow-100 text-yellow-700">Disabled</span>
                    )}
                  </td>
                  <td className="px-6 py-3 text-sm text-gray-600 whitespace-nowrap">
                    {m.last_login_at
                      ? formatDate(m.last_login_at, { year: 'numeric', month: 'short', day: 'numeric' })
                      : '—'}
                  </td>
                  {isAdmin && (
                    <td className="px-6 py-3 text-right whitespace-nowrap space-x-2">
                      {!m.is_self && (
                        <>
                          <button
                            onClick={() => updateMutation.mutate({
                              userId: m.id,
                              patch: { is_customer_admin: !m.is_customer_admin },
                            })}
                            className="text-xs text-odc-600 hover:text-odc-700"
                            disabled={updateMutation.isPending}
                          >
                            {m.is_customer_admin ? 'Demote' : 'Promote'}
                          </button>
                          <button
                            onClick={() => updateMutation.mutate({
                              userId: m.id,
                              patch: { is_active: !m.is_active },
                            })}
                            className="text-xs text-yellow-700 hover:text-yellow-800"
                            disabled={updateMutation.isPending}
                          >
                            {m.is_active ? 'Disable' : 'Enable'}
                          </button>
                          <button
                            onClick={() => {
                              if (window.confirm(`Remove ${m.email} from your team?`)) {
                                removeMutation.mutate(m.id)
                              }
                            }}
                            className="text-xs text-red-600 hover:text-red-700"
                            disabled={removeMutation.isPending}
                          >
                            Remove
                          </button>
                        </>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export default CustomerAccount
