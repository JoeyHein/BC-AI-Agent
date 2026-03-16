import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { installReferralsApi } from '../../api/customerClient'

/**
 * Embeddable install referral form for home builders.
 * Can be used standalone or embedded within a quote/lot flow.
 *
 * Props:
 * - orderRef: optional order/quote reference to attach
 * - lotAddress: optional address to pre-fill
 * - onSuccess: callback after successful submission
 * - compact: if true, uses a more compact layout
 */
function InstallReferralForm({ orderRef, lotAddress, onSuccess, compact = false }) {
  const [wantsInstall, setWantsInstall] = useState(false)
  const [formData, setFormData] = useState({
    site_address: lotAddress || '',
    contact_name: '',
    contact_phone: '',
    preferred_date: '',
    access_notes: '',
  })
  const [submitted, setSubmitted] = useState(false)

  const createMutation = useMutation({
    mutationFn: (data) => installReferralsApi.create(data),
    onSuccess: () => {
      setSubmitted(true)
      onSuccess?.()
    }
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    createMutation.mutate({
      ...formData,
      order_ref: orderRef || undefined,
    })
  }

  const updateField = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }))
  }

  // After successful submission, show confirmation
  if (submitted) {
    return (
      <div className={`bg-green-50 border border-green-200 rounded-lg ${compact ? 'p-3' : 'p-4'}`}>
        <div className="flex items-center">
          <CheckCircleIcon className="h-5 w-5 text-green-600 mr-2 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-green-800">Install referral submitted</p>
            <p className="text-xs text-green-700 mt-0.5">
              We'll connect you with a qualified installer and confirm the schedule.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={`border border-gray-200 rounded-lg ${compact ? 'p-3' : 'p-4'}`}>
      {/* Checkbox toggle */}
      <label className="flex items-center cursor-pointer">
        <input
          type="checkbox"
          checked={wantsInstall}
          onChange={(e) => setWantsInstall(e.target.checked)}
          className="h-4 w-4 text-odc-600 focus:ring-odc-500 border-gray-300 rounded"
        />
        <span className={`ml-2 ${compact ? 'text-sm' : 'text-sm'} font-medium text-gray-700`}>
          I'd like installation arranged
        </span>
      </label>

      {wantsInstall && (
        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Site Address <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              value={formData.site_address}
              onChange={(e) => updateField('site_address', e.target.value)}
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
              placeholder="123 Main St, Vancouver, BC"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Contact Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                value={formData.contact_name}
                onChange={(e) => updateField('contact_name', e.target.value)}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                placeholder="Site contact name"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">
                Contact Phone <span className="text-red-500">*</span>
              </label>
              <input
                type="tel"
                required
                value={formData.contact_phone}
                onChange={(e) => updateField('contact_phone', e.target.value)}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                placeholder="(604) 555-0123"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">Preferred Date</label>
            <input
              type="date"
              value={formData.preferred_date}
              onChange={(e) => updateField('preferred_date', e.target.value)}
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">Access Notes</label>
            <textarea
              value={formData.access_notes}
              onChange={(e) => updateField('access_notes', e.target.value)}
              rows={2}
              className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
              placeholder="Gate code, site hours, special instructions..."
            />
          </div>

          {createMutation.error && (
            <div className="bg-red-50 border border-red-200 rounded p-3">
              <p className="text-sm text-red-700">
                {createMutation.error?.response?.data?.detail || 'Failed to submit referral. Please try again.'}
              </p>
            </div>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
            >
              {createMutation.isPending ? 'Submitting...' : 'Request Installation'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

function CheckCircleIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

export default InstallReferralForm
