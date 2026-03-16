import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { installReferralsAdminApi } from '../api/client'

const STATUS_OPTIONS = [
  { value: 'new', label: 'New', color: 'bg-amber-100 text-amber-800' },
  { value: 'scheduled', label: 'Scheduled', color: 'bg-blue-100 text-blue-800' },
  { value: 'complete', label: 'Complete', color: 'bg-green-100 text-green-800' },
]

const STATUS_COLOR_MAP = {
  new: 'bg-amber-100 text-amber-800',
  scheduled: 'bg-blue-100 text-blue-800',
  complete: 'bg-green-100 text-green-800',
}

function StatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_COLOR_MAP[status] || 'bg-gray-100 text-gray-800'}`}>
      {status ? status.charAt(0).toUpperCase() + status.slice(1) : 'Unknown'}
    </span>
  )
}

function InstallReferralQueue() {
  const [filter, setFilter] = useState('all')
  const [expandedId, setExpandedId] = useState(null)
  const queryClient = useQueryClient()

  // Fetch referrals
  const { data: referrals, isLoading, error } = useQuery({
    queryKey: ['installReferrals', filter],
    queryFn: async () => {
      const params = filter !== 'all' ? { status: filter } : {}
      const response = await installReferralsAdminApi.list(params)
      return response.data
    }
  })

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => installReferralsAdminApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['installReferrals'] })
    }
  })

  const allReferrals = referrals?.referrals || referrals || []

  // Count by status (from unfiltered data or from all referrals)
  const counts = {
    all: allReferrals.length,
    new: allReferrals.filter(r => r.status === 'new').length,
    scheduled: allReferrals.filter(r => r.status === 'scheduled').length,
    complete: allReferrals.filter(r => r.status === 'complete').length,
  }

  const tabs = [
    { key: 'all', label: 'All', count: counts.all },
    { key: 'new', label: 'New', count: counts.new },
    { key: 'scheduled', label: 'Scheduled', count: counts.scheduled },
    { key: 'complete', label: 'Complete', count: counts.complete },
  ]

  const handleRowClick = (id) => {
    setExpandedId(expandedId === id ? null : id)
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Install Referrals</h1>
          <p className="mt-1 text-sm text-gray-500">Manage installation referral requests from home builders</p>
        </div>
        <div className="flex justify-center items-center h-64">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Install Referrals</h1>
          <p className="mt-1 text-sm text-gray-500">Manage installation referral requests from home builders</p>
        </div>
        <div className="bg-red-50 p-4 rounded-md">
          <p className="text-red-700">Failed to load install referrals. Please try again.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Install Referrals</h1>
        <p className="mt-1 text-sm text-gray-500">Manage installation referral requests from home builders</p>
      </div>

      {/* Filter tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={`whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm ${
                filter === tab.key
                  ? 'border-odc-500 text-odc-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {tab.label}
              <span className={`ml-2 py-0.5 px-2.5 rounded-full text-xs ${
                filter === tab.key ? 'bg-blue-100 text-odc-600' : 'bg-gray-100 text-gray-900'
              }`}>
                {tab.count}
              </span>
            </button>
          ))}
        </nav>
      </div>

      {/* Table */}
      {allReferrals.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <ClipboardIcon className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-2 text-sm font-medium text-gray-900">No referrals</h3>
          <p className="mt-1 text-sm text-gray-500">
            {filter === 'all'
              ? 'No install referral requests yet.'
              : `No ${filter} referrals found.`}
          </p>
        </div>
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Customer</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Order Ref</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Site Address</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Requested Date</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Assigned Sub</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Scheduled Date</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {allReferrals.map((referral) => (
                  <ReferralRow
                    key={referral.id}
                    referral={referral}
                    isExpanded={expandedId === referral.id}
                    onToggle={() => handleRowClick(referral.id)}
                    onUpdate={(data) => updateMutation.mutate({ id: referral.id, data })}
                    isUpdating={updateMutation.isPending && updateMutation.variables?.id === referral.id}
                    updateError={updateMutation.error?.response?.data?.detail}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function ReferralRow({ referral, isExpanded, onToggle, onUpdate, isUpdating, updateError }) {
  const [editData, setEditData] = useState({
    status: referral.status || 'new',
    assigned_sub: referral.assigned_sub || '',
    scheduled_date: referral.scheduled_date || '',
    internal_notes: referral.internal_notes || '',
  })

  // Reset form when referral changes
  const handleToggle = () => {
    if (!isExpanded) {
      setEditData({
        status: referral.status || 'new',
        assigned_sub: referral.assigned_sub || '',
        scheduled_date: referral.scheduled_date || '',
        internal_notes: referral.internal_notes || '',
      })
    }
    onToggle()
  }

  const handleSave = () => {
    onUpdate(editData)
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return '-'
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
    } catch {
      return dateStr
    }
  }

  return (
    <>
      <tr
        className={`hover:bg-gray-50 cursor-pointer ${isExpanded ? 'bg-odc-50' : ''}`}
        onClick={handleToggle}
      >
        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
          {referral.customer_name || '-'}
        </td>
        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
          {referral.order_ref || referral.quote_ref || '-'}
        </td>
        <td className="px-6 py-4 text-sm text-gray-700 max-w-xs truncate">
          {referral.site_address || '-'}
        </td>
        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
          {formatDate(referral.preferred_date)}
        </td>
        <td className="px-6 py-4 whitespace-nowrap">
          <StatusBadge status={referral.status} />
        </td>
        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
          {referral.assigned_sub || '-'}
        </td>
        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
          {formatDate(referral.scheduled_date)}
        </td>
      </tr>

      {/* Expanded edit panel */}
      {isExpanded && (
        <tr>
          <td colSpan={7} className="px-6 py-4 bg-gray-50 border-t border-gray-100">
            <div className="max-w-3xl">
              {/* Referral details */}
              <div className="mb-4 grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="font-medium text-gray-700">Contact Name:</span>{' '}
                  <span className="text-gray-600">{referral.contact_name || '-'}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">Contact Phone:</span>{' '}
                  <span className="text-gray-600">{referral.contact_phone || '-'}</span>
                </div>
                <div className="col-span-2">
                  <span className="font-medium text-gray-700">Access Notes:</span>{' '}
                  <span className="text-gray-600">{referral.access_notes || '-'}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">Created:</span>{' '}
                  <span className="text-gray-600">{formatDate(referral.created_at)}</span>
                </div>
              </div>

              {/* Edit form */}
              <div className="border-t border-gray-200 pt-4 space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Status</label>
                    <select
                      value={editData.status}
                      onChange={(e) => setEditData({ ...editData, status: e.target.value })}
                      className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                    >
                      {STATUS_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700">Assigned Sub</label>
                    <input
                      type="text"
                      value={editData.assigned_sub}
                      onChange={(e) => setEditData({ ...editData, assigned_sub: e.target.value })}
                      className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                      placeholder="Installer name"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700">Scheduled Date</label>
                    <input
                      type="date"
                      value={editData.scheduled_date}
                      onChange={(e) => setEditData({ ...editData, scheduled_date: e.target.value })}
                      className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700">Internal Notes</label>
                  <textarea
                    value={editData.internal_notes}
                    onChange={(e) => setEditData({ ...editData, internal_notes: e.target.value })}
                    rows={3}
                    className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                    placeholder="Internal notes about this referral..."
                  />
                </div>

                {updateError && (
                  <div className="bg-red-50 border border-red-200 rounded p-3">
                    <p className="text-sm text-red-700">{updateError}</p>
                  </div>
                )}

                <div className="flex justify-end">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleSave()
                    }}
                    disabled={isUpdating}
                    className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
                  >
                    {isUpdating ? 'Saving...' : 'Save Changes'}
                  </button>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function ClipboardIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
    </svg>
  )
}

export default InstallReferralQueue
