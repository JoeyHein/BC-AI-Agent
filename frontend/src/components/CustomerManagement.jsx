import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient, { customersApi } from '../api/client'

// API functions
const fetchCustomers = async () => {
  const response = await apiClient.get('/api/admin/customers')
  return response.data
}

const fetchBCCustomers = async (query = '') => {
  const response = await apiClient.get('/api/admin/customers/bc-customers', {
    params: query ? { q: query } : {}
  })
  return response.data
}

const createCustomer = async (data) => {
  const response = await apiClient.post('/api/admin/customers', data)
  return response.data
}

const updateCustomer = async ({ id, data }) => {
  const response = await apiClient.patch(`/api/admin/customers/${id}`, data)
  return response.data
}

const linkCustomer = async ({ id, bc_customer_id }) => {
  const response = await apiClient.post(`/api/admin/customers/${id}/link`, { bc_customer_id })
  return response.data
}

const unlinkCustomer = async (id) => {
  const response = await apiClient.post(`/api/admin/customers/${id}/unlink`)
  return response.data
}

const deleteCustomer = async (id) => {
  const response = await apiClient.delete(`/api/admin/customers/${id}`)
  return response.data
}

const syncBCCustomers = async () => {
  const response = await apiClient.post('/api/admin/customers/sync-bc-customers')
  return response.data
}

const bulkCreateFromBC = async () => {
  const response = await apiClient.post('/api/admin/customers/bulk-create-from-bc')
  return response.data
}

const fetchCustomerActivity = async (id) => {
  const response = await apiClient.get(`/api/admin/customers/${id}/activity`)
  return response.data
}

const resetCustomerPassword = async (id) => {
  const response = await apiClient.post(`/api/admin/customers/${id}/reset-password`)
  return response.data
}

// Pricing Tier Badge
const TIER_STYLES = {
  gold: 'bg-amber-100 text-amber-800',
  silver: 'bg-gray-200 text-gray-700',
  bronze: 'bg-orange-100 text-orange-800',
  retail: 'bg-blue-100 text-blue-800',
}

function PricingTierBadge({ tier }) {
  if (!tier || !TIER_STYLES[tier]) {
    return <span className="text-sm text-gray-400">Not set</span>
  }
  return (
    <span className={`inline-flex px-2 text-xs leading-5 font-semibold rounded-full capitalize ${TIER_STYLES[tier]}`}>
      {tier}
    </span>
  )
}

// Customer List Component
function CustomerList({ customers, onSelect, selectedId }) {
  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Customer
            </th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              BC Account
            </th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Pricing Tier
            </th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Status
            </th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Quotes
            </th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Created
            </th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {customers.map((customer) => (
            <tr
              key={customer.id}
              onClick={() => onSelect(customer)}
              className={`cursor-pointer hover:bg-gray-50 ${
                selectedId === customer.id ? 'bg-odc-50' : ''
              }`}
            >
              <td className="px-6 py-4 whitespace-nowrap">
                <div className="flex items-center">
                  <div className="flex-shrink-0 h-10 w-10">
                    <div className="h-10 w-10 rounded-full bg-odc-100 flex items-center justify-center">
                      <span className="text-odc-600 font-medium text-sm">
                        {customer.name?.charAt(0) || customer.email.charAt(0).toUpperCase()}
                      </span>
                    </div>
                  </div>
                  <div className="ml-4">
                    <div className="text-sm font-medium text-gray-900">
                      {customer.name || 'No name'}
                    </div>
                    <div className="text-sm text-gray-500">{customer.email}</div>
                  </div>
                </div>
              </td>
              <td className="px-6 py-4 whitespace-nowrap">
                {customer.bc_customer_id ? (
                  <div>
                    <div className="text-sm text-gray-900">{customer.bc_company_name}</div>
                    <div className="text-sm text-gray-500">{customer.bc_customer_id}</div>
                  </div>
                ) : (
                  <span className="text-sm text-gray-400">Not linked</span>
                )}
              </td>
              <td className="px-6 py-4 whitespace-nowrap">
                <PricingTierBadge tier={customer.pricing_tier} />
              </td>
              <td className="px-6 py-4 whitespace-nowrap">
                <div className="flex flex-col gap-1">
                  <span
                    className={`inline-flex px-2 text-xs leading-5 font-semibold rounded-full ${
                      customer.is_active
                        ? 'bg-green-100 text-green-800'
                        : 'bg-red-100 text-red-800'
                    }`}
                  >
                    {customer.is_active ? 'Active' : 'Inactive'}
                  </span>
                  {customer.email_verified ? (
                    <span className="inline-flex px-2 text-xs leading-5 font-semibold rounded-full bg-blue-100 text-blue-800">
                      Verified
                    </span>
                  ) : (
                    <span className="inline-flex px-2 text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800">
                      Unverified
                    </span>
                  )}
                </div>
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                {customer.saved_quotes_count}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                {new Date(customer.created_at).toLocaleDateString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {customers.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          No customer accounts found
        </div>
      )}
    </div>
  )
}

// Customer Detail Panel
function CustomerDetail({ customer, onClose, onRefresh }) {
  const queryClient = useQueryClient()
  const [showLinkModal, setShowLinkModal] = useState(false)
  const [editing, setEditing] = useState(false)
  const [resetLink, setResetLink] = useState(null)
  const [editForm, setEditForm] = useState({
    name: customer?.name || '',
    is_active: customer?.is_active ?? true,
    email_verified: customer?.email_verified ?? false
  })

  useEffect(() => {
    if (customer) {
      setEditForm({
        name: customer.name || '',
        is_active: customer.is_active ?? true,
        email_verified: customer.email_verified ?? false
      })
    }
  }, [customer])

  const updateMutation = useMutation({
    mutationFn: updateCustomer,
    onSuccess: () => {
      queryClient.invalidateQueries(['customers'])
      setEditing(false)
      onRefresh()
    }
  })

  const unlinkMutation = useMutation({
    mutationFn: unlinkCustomer,
    onSuccess: () => {
      queryClient.invalidateQueries(['customers'])
      onRefresh()
    }
  })

  const deleteMutation = useMutation({
    mutationFn: deleteCustomer,
    onSuccess: () => {
      queryClient.invalidateQueries(['customers'])
      onClose()
    }
  })

  const resetPasswordMutation = useMutation({
    mutationFn: () => resetCustomerPassword(customer.id),
    onSuccess: (data) => {
      setResetLink(data.reset_link)
    }
  })

  const { data: activity } = useQuery({
    queryKey: ['customer-activity', customer?.id],
    queryFn: () => fetchCustomerActivity(customer.id),
    enabled: !!customer?.id
  })

  const handleSave = () => {
    updateMutation.mutate({
      id: customer.id,
      data: editForm
    })
  }

  const handleDelete = () => {
    if (window.confirm(`Are you sure you want to delete the account for ${customer.email}? This cannot be undone.`)) {
      deleteMutation.mutate(customer.id)
    }
  }

  if (!customer) return null

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h3 className="text-lg font-medium text-gray-900">Customer Details</h3>
          <p className="text-sm text-gray-500">{customer.email}</p>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-500"
        >
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {editing ? (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">Name</label>
            <input
              type="text"
              value={editForm.name}
              onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
            />
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center">
              <input
                type="checkbox"
                checked={editForm.is_active}
                onChange={(e) => setEditForm({ ...editForm, is_active: e.target.checked })}
                className="h-4 w-4 text-odc-600 focus:ring-odc-500 border-gray-300 rounded"
              />
              <span className="ml-2 text-sm text-gray-700">Active</span>
            </label>
            <label className="flex items-center">
              <input
                type="checkbox"
                checked={editForm.email_verified}
                onChange={(e) => setEditForm({ ...editForm, email_verified: e.target.checked })}
                className="h-4 w-4 text-odc-600 focus:ring-odc-500 border-gray-300 rounded"
              />
              <span className="ml-2 text-sm text-gray-700">Email Verified</span>
            </label>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleSave}
              disabled={updateMutation.isLoading}
              className="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
            >
              {updateMutation.isLoading ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="inline-flex items-center px-3 py-2 border border-gray-300 text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <dt className="text-sm font-medium text-gray-500">Name</dt>
              <dd className="mt-1 text-sm text-gray-900">{customer.name || '-'}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Status</dt>
              <dd className="mt-1">
                <span
                  className={`inline-flex px-2 text-xs leading-5 font-semibold rounded-full ${
                    customer.is_active
                      ? 'bg-green-100 text-green-800'
                      : 'bg-red-100 text-red-800'
                  }`}
                >
                  {customer.is_active ? 'Active' : 'Inactive'}
                </span>
              </dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Email Verified</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {customer.email_verified ? 'Yes' : 'No'}
              </dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Created</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {new Date(customer.created_at).toLocaleString()}
              </dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Last Login</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {customer.last_login_at
                  ? new Date(customer.last_login_at).toLocaleString()
                  : 'Never'}
              </dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Saved Quotes</dt>
              <dd className="mt-1 text-sm text-gray-900">{customer.saved_quotes_count}</dd>
            </div>
          </div>

          <div className="border-t border-gray-200 pt-4">
            <h4 className="text-sm font-medium text-gray-900 mb-2">BC Customer Link</h4>
            {customer.bc_customer_id ? (
              <div className="bg-gray-50 rounded-md p-3">
                <div className="text-sm">
                  <p className="font-medium text-gray-900">{customer.bc_company_name}</p>
                  <p className="text-gray-500">ID: {customer.bc_customer_id}</p>
                  <div className="mt-2">
                    <label className="text-xs font-medium text-gray-500">Pricing Tier</label>
                    <div className="mt-1 flex items-center gap-2">
                      <select
                        value={customer.pricing_tier || ''}
                        onChange={async (e) => {
                          const newTier = e.target.value || null
                          try {
                            await customersApi.updatePricingTier(customer.id, newTier)
                            onRefresh()
                          } catch (err) {
                            console.error('Failed to update pricing tier:', err)
                            alert(err.response?.data?.detail || 'Failed to update pricing tier')
                          }
                        }}
                        disabled={!customer.bc_customer_id}
                        className="border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500 disabled:opacity-50"
                      >
                        <option value="">Not set</option>
                        <option value="gold">Gold</option>
                        <option value="silver">Silver</option>
                        <option value="bronze">Bronze</option>
                        <option value="retail">Retail</option>
                      </select>
                      <PricingTierBadge tier={customer.pricing_tier} />
                    </div>
                  </div>
                  {customer.bc_contact_name && (
                    <p className="text-gray-500">Contact: {customer.bc_contact_name}</p>
                  )}
                  {customer.bc_email && (
                    <p className="text-gray-500">Email: {customer.bc_email}</p>
                  )}
                  {customer.bc_phone && (
                    <p className="text-gray-500">Phone: {customer.bc_phone}</p>
                  )}
                </div>
                <button
                  onClick={() => unlinkMutation.mutate(customer.id)}
                  disabled={unlinkMutation.isLoading}
                  className="mt-2 text-sm text-red-600 hover:text-red-800"
                >
                  {unlinkMutation.isLoading ? 'Unlinking...' : 'Unlink BC Customer'}
                </button>
              </div>
            ) : (
              <div>
                <p className="text-sm text-gray-500 mb-2">
                  This customer is not linked to a BC customer account.
                </p>
                <button
                  onClick={() => setShowLinkModal(true)}
                  className="inline-flex items-center px-3 py-2 border border-gray-300 text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
                >
                  Link to BC Customer
                </button>
              </div>
            )}
          </div>

          {/* Activity Section */}
          {activity && (
            <div className="border-t border-gray-200 pt-4">
              <h4 className="text-sm font-medium text-gray-900 mb-2">Activity</h4>

              {/* Saved Quotes */}
              {activity.quotes?.length > 0 && (
                <div className="mb-3">
                  <p className="text-xs font-medium text-gray-500 uppercase mb-1">Saved Quotes ({activity.quotes.length})</p>
                  <div className="max-h-32 overflow-y-auto space-y-1">
                    {activity.quotes.map((q) => (
                      <div key={q.id} className="flex items-center justify-between text-xs bg-gray-50 rounded px-2 py-1">
                        <span className="text-gray-900 truncate mr-2">{q.name || 'Unnamed'}</span>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          <span className={`px-1.5 py-0.5 rounded-full font-medium ${
                            q.status === 'submitted' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
                          }`}>
                            {q.status}
                          </span>
                          <span className="text-gray-400">{q.created_at ? new Date(q.created_at).toLocaleDateString() : ''}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Orders */}
              {activity.orders?.length > 0 && (
                <div className="mb-3">
                  <p className="text-xs font-medium text-gray-500 uppercase mb-1">Orders ({activity.orders.length})</p>
                  <div className="max-h-32 overflow-y-auto space-y-1">
                    {activity.orders.map((o) => (
                      <div key={o.id} className="flex items-center justify-between text-xs bg-gray-50 rounded px-2 py-1">
                        <span className="text-gray-900">{o.bc_order_number || `#${o.id}`}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-gray-600">{o.status}</span>
                          {o.total_amount && <span className="text-gray-900 font-medium">${o.total_amount.toLocaleString()}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {!activity.quotes?.length && !activity.orders?.length && (
                <p className="text-xs text-gray-400">No activity yet</p>
              )}
            </div>
          )}

          <div className="flex gap-2 pt-4 border-t border-gray-200">
            <button
              onClick={() => setEditing(true)}
              className="inline-flex items-center px-3 py-2 border border-gray-300 text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
            >
              Edit
            </button>
            <button
              onClick={() => resetPasswordMutation.mutate()}
              disabled={resetPasswordMutation.isPending}
              className="inline-flex items-center px-3 py-2 border border-gray-300 text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
            >
              {resetPasswordMutation.isPending ? 'Generating...' : 'Reset Password'}
            </button>
            <button
              onClick={handleDelete}
              disabled={deleteMutation.isLoading}
              className="inline-flex items-center px-3 py-2 border border-red-300 text-sm leading-4 font-medium rounded-md text-red-700 bg-white hover:bg-red-50"
            >
              {deleteMutation.isLoading ? 'Deleting...' : 'Delete Account'}
            </button>
          </div>

          {/* Reset Password Link Dialog */}
          {resetLink && (
            <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded-md">
              <p className="text-sm font-medium text-blue-900 mb-1">Password Reset Link (expires in 1 hour)</p>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={resetLink}
                  className="flex-1 text-xs bg-white border border-blue-300 rounded px-2 py-1 font-mono"
                />
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(resetLink)
                    alert('Link copied to clipboard!')
                  }}
                  className="inline-flex items-center px-2 py-1 border border-blue-300 text-xs font-medium rounded-md text-blue-700 bg-white hover:bg-blue-50"
                >
                  Copy
                </button>
              </div>
              <button
                onClick={() => setResetLink(null)}
                className="mt-1 text-xs text-blue-600 hover:text-blue-800"
              >
                Dismiss
              </button>
            </div>
          )}
        </div>
      )}

      {showLinkModal && (
        <LinkBCCustomerModal
          customerId={customer.id}
          onClose={() => setShowLinkModal(false)}
          onSuccess={() => {
            setShowLinkModal(false)
            queryClient.invalidateQueries(['customers'])
            onRefresh()
          }}
        />
      )}
    </div>
  )
}

// Link BC Customer Modal
function LinkBCCustomerModal({ customerId, onClose, onSuccess }) {
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(searchQuery)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  const { data: bcCustomers, isLoading } = useQuery({
    queryKey: ['bc-customers', debouncedQuery],
    queryFn: () => fetchBCCustomers(debouncedQuery),
    enabled: true
  })

  const linkMutation = useMutation({
    mutationFn: linkCustomer,
    onSuccess
  })

  const handleLink = (bcCustomerId) => {
    linkMutation.mutate({ id: customerId, bc_customer_id: bcCustomerId })
  }

  return (
    <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-medium text-gray-900">Link to BC Customer</h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-500">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className="mt-4">
            <input
              type="text"
              placeholder="Search by company name, contact, or email..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {isLoading ? (
            <div className="text-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-odc-600 mx-auto"></div>
            </div>
          ) : bcCustomers?.length > 0 ? (
            <div className="space-y-2">
              {bcCustomers.map((bc) => (
                <div
                  key={bc.bc_customer_id}
                  className={`border rounded-lg p-4 ${
                    bc.already_linked
                      ? 'bg-gray-50 border-gray-200'
                      : 'hover:border-odc-300 cursor-pointer'
                  }`}
                  onClick={() => !bc.already_linked && handleLink(bc.bc_customer_id)}
                >
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="font-medium text-gray-900">{bc.company_name || 'No name'}</p>
                      <p className="text-sm text-gray-500">ID: {bc.bc_customer_id}</p>
                      {bc.contact_name && (
                        <p className="text-sm text-gray-500">Contact: {bc.contact_name}</p>
                      )}
                      {bc.email && <p className="text-sm text-gray-500">Email: {bc.email}</p>}
                    </div>
                    {bc.already_linked ? (
                      <span className="inline-flex px-2 py-1 text-xs font-medium rounded-full bg-gray-100 text-gray-600">
                        Already linked
                      </span>
                    ) : (
                      <span className="inline-flex px-2 py-1 text-xs font-medium rounded-full bg-odc-100 text-odc-600">
                        Click to link
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              {debouncedQuery
                ? 'No BC customers found matching your search'
                : 'Enter a search term to find BC customers'}
            </div>
          )}
        </div>

        {linkMutation.isLoading && (
          <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
            <div className="flex items-center justify-center text-sm text-gray-500">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-odc-600 mr-2"></div>
              Linking customer...
            </div>
          </div>
        )}

        {linkMutation.isError && (
          <div className="px-6 py-4 border-t border-gray-200 bg-red-50">
            <p className="text-sm text-red-600">
              Error: {linkMutation.error?.response?.data?.detail || 'Failed to link customer'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

// Create Customer Modal
function CreateCustomerModal({ onClose, onSuccess }) {
  const [formData, setFormData] = useState({
    email: '',
    name: '',
    password: '',
    bc_customer_id: ''
  })
  const [showBCSearch, setShowBCSearch] = useState(false)
  const [bcSearchQuery, setBCSearchQuery] = useState('')
  const [selectedBC, setSelectedBC] = useState(null)

  const { data: bcCustomers } = useQuery({
    queryKey: ['bc-customers', bcSearchQuery],
    queryFn: () => fetchBCCustomers(bcSearchQuery),
    enabled: showBCSearch && bcSearchQuery.length > 0
  })

  const createMutation = useMutation({
    mutationFn: createCustomer,
    onSuccess
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    createMutation.mutate({
      ...formData,
      bc_customer_id: selectedBC?.bc_customer_id || null
    })
  }

  return (
    <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-medium text-gray-900">Create Customer Account</h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-500">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">Email *</label>
            <input
              type="email"
              required
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">Name *</label>
            <input
              type="text"
              required
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">Password *</label>
            <input
              type="password"
              required
              minLength={8}
              value={formData.password}
              onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
            />
            <p className="mt-1 text-xs text-gray-500">Minimum 8 characters</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">Link to BC Customer (optional)</label>
            {selectedBC ? (
              <div className="mt-1 flex items-center justify-between p-3 bg-gray-50 rounded-md">
                <div>
                  <p className="text-sm font-medium">{selectedBC.company_name}</p>
                  <p className="text-xs text-gray-500">{selectedBC.bc_customer_id}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedBC(null)}
                  className="text-sm text-red-600 hover:text-red-800"
                >
                  Remove
                </button>
              </div>
            ) : showBCSearch ? (
              <div className="mt-1">
                <input
                  type="text"
                  placeholder="Search BC customers..."
                  value={bcSearchQuery}
                  onChange={(e) => setBCSearchQuery(e.target.value)}
                  className="block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                />
                {bcCustomers?.length > 0 && (
                  <div className="mt-2 max-h-40 overflow-y-auto border rounded-md">
                    {bcCustomers.filter(bc => !bc.already_linked).map((bc) => (
                      <div
                        key={bc.bc_customer_id}
                        onClick={() => {
                          setSelectedBC(bc)
                          setShowBCSearch(false)
                          setBCSearchQuery('')
                        }}
                        className="p-2 hover:bg-gray-50 cursor-pointer border-b last:border-b-0"
                      >
                        <p className="text-sm font-medium">{bc.company_name}</p>
                        <p className="text-xs text-gray-500">{bc.bc_customer_id}</p>
                      </div>
                    ))}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => setShowBCSearch(false)}
                  className="mt-2 text-sm text-gray-500 hover:text-gray-700"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowBCSearch(true)}
                className="mt-1 text-sm text-odc-600 hover:text-odc-800"
              >
                + Link to BC customer
              </button>
            )}
          </div>

          {createMutation.isError && (
            <div className="bg-red-50 text-red-600 text-sm p-3 rounded-md">
              {createMutation.error?.response?.data?.detail || 'Failed to create customer'}
            </div>
          )}

          <div className="flex gap-2 pt-4">
            <button
              type="submit"
              disabled={createMutation.isLoading}
              className="flex-1 inline-flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
            >
              {createMutation.isLoading ? 'Creating...' : 'Create Account'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// Main Component
function CustomerManagement() {
  const [selectedCustomer, setSelectedCustomer] = useState(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const queryClient = useQueryClient()

  const { data: customers, isLoading, error, refetch } = useQuery({
    queryKey: ['customers'],
    queryFn: fetchCustomers
  })

  const syncMutation = useMutation({
    mutationFn: syncBCCustomers,
    onSuccess: (data) => {
      queryClient.invalidateQueries(['customers'])
      queryClient.invalidateQueries(['bc-customers'])
      alert(`Sync complete: ${data.customers_synced} new, ${data.customers_updated} updated${data.errors?.length ? `\nErrors: ${data.errors.join(', ')}` : ''}`)
    },
    onError: (err) => {
      alert(`Sync failed: ${err.response?.data?.detail || err.message}`)
    }
  })

  const bulkCreateMutation = useMutation({
    mutationFn: bulkCreateFromBC,
    onSuccess: (data) => {
      queryClient.invalidateQueries(['customers'])
      alert(
        `Bulk Create Complete:\n` +
        `- Created: ${data.created}\n` +
        `- Skipped (existing): ${data.skipped_existing}\n` +
        `- Skipped (no email): ${data.skipped_no_email}\n` +
        `- Skipped (Amazon): ${data.skipped_amazon}` +
        (data.errors?.length ? `\n- Errors: ${data.errors.length}` : '')
      )
    },
    onError: (err) => {
      alert(`Bulk create failed: ${err.response?.data?.detail || err.message}`)
    }
  })

  const handleSelectCustomer = async (customer) => {
    // Fetch full details
    try {
      const response = await apiClient.get(`/api/admin/customers/${customer.id}`)
      setSelectedCustomer(response.data)
    } catch (err) {
      console.error('Failed to fetch customer details:', err)
      setSelectedCustomer(customer)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 text-red-600 p-4 rounded-md">
        Failed to load customers: {error.message}
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Customer Portal Management</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage customer portal accounts and BC customer links
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isLoading}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50"
          >
            {syncMutation.isLoading ? (
              <svg className="animate-spin h-5 w-5 mr-2 text-gray-500" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            ) : (
              <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            )}
            {syncMutation.isLoading ? 'Syncing...' : 'Sync BC Customers'}
          </button>
          <button
            onClick={() => {
              if (window.confirm(
                'Bulk Create Portal Accounts\n\n' +
                'This will create customer portal accounts for all BC customers that:\n' +
                '- Have an email address\n' +
                '- Don\'t already have a portal account\n' +
                '- Are not Amazon customers\n\n' +
                'Accounts will be created silently (no emails sent).\n\n' +
                'Continue?'
              )) {
                bulkCreateMutation.mutate()
              }
            }}
            disabled={bulkCreateMutation.isPending}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50"
          >
            {bulkCreateMutation.isPending ? (
              <svg className="animate-spin h-5 w-5 mr-2 text-gray-500" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            ) : (
              <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            )}
            {bulkCreateMutation.isPending ? 'Creating...' : 'Bulk Create from BC'}
          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
          >
            <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Create Customer
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className={selectedCustomer ? 'lg:col-span-2' : 'lg:col-span-3'}>
          <CustomerList
            customers={customers || []}
            onSelect={handleSelectCustomer}
            selectedId={selectedCustomer?.id}
          />
        </div>

        {selectedCustomer && (
          <div className="lg:col-span-1">
            <CustomerDetail
              customer={selectedCustomer}
              onClose={() => setSelectedCustomer(null)}
              onRefresh={() => handleSelectCustomer(selectedCustomer)}
            />
          </div>
        )}
      </div>

      {showCreateModal && (
        <CreateCustomerModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            setShowCreateModal(false)
            queryClient.invalidateQueries(['customers'])
          }}
        />
      )}
    </div>
  )
}

export default CustomerManagement
