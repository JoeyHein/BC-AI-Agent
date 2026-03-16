import { useQuery } from '@tanstack/react-query'
import { installReferralsApi } from '../../api/customerClient'

const STATUS_COLORS = {
  new: 'bg-amber-100 text-amber-800',
  scheduled: 'bg-blue-100 text-blue-800',
  complete: 'bg-green-100 text-green-800',
}

const STATUS_LABELS = {
  new: 'Pending',
  scheduled: 'Scheduled',
  complete: 'Complete',
}

/**
 * Compact install referral status display.
 * Shows a single status line with badge. Suitable for embedding in
 * order detail, project lot detail, etc.
 *
 * Props:
 * - referral: referral object (if already loaded)
 *   OR
 * - referralId: ID to fetch
 */
function InstallReferralStatus({ referral: propReferral, referralId }) {
  const { data: fetchedReferral } = useQuery({
    queryKey: ['installReferral', referralId],
    queryFn: async () => {
      const response = await installReferralsApi.get(referralId)
      return response.data
    },
    enabled: !!referralId && !propReferral,
  })

  const referral = propReferral || fetchedReferral
  if (!referral) return null

  return (
    <div className="flex items-center space-x-3 text-sm">
      <WrenchIcon className="h-4 w-4 text-gray-400 flex-shrink-0" />
      <span className="text-gray-600">Install:</span>
      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[referral.status] || 'bg-gray-100 text-gray-800'}`}>
        {STATUS_LABELS[referral.status] || referral.status}
      </span>
      {referral.status === 'scheduled' && referral.scheduled_date && (
        <span className="text-gray-600">
          {new Date(referral.scheduled_date).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
          })}
        </span>
      )}
    </div>
  )
}

/**
 * List all install referrals for the current customer.
 * Minimal display for embedding in dashboard or orders page.
 */
function InstallReferralList() {
  const { data: referrals, isLoading } = useQuery({
    queryKey: ['myInstallReferrals'],
    queryFn: async () => {
      const response = await installReferralsApi.list()
      return response.data
    }
  })

  if (isLoading) return null

  const items = referrals?.referrals || referrals || []
  if (items.length === 0) return null

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
      <div className="px-6 py-4 border-b border-gray-200">
        <h3 className="text-base font-medium text-gray-900">Install Referrals</h3>
      </div>
      <div className="divide-y divide-gray-100">
        {items.map((referral) => (
          <div key={referral.id} className="px-6 py-3 flex items-center justify-between">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-gray-900 truncate">
                {referral.site_address || 'No address'}
              </p>
              {referral.order_ref && (
                <p className="text-xs text-gray-500">Ref: {referral.order_ref}</p>
              )}
            </div>
            <div className="ml-4 flex items-center space-x-3">
              <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[referral.status] || 'bg-gray-100 text-gray-800'}`}>
                {STATUS_LABELS[referral.status] || referral.status}
              </span>
              {referral.status === 'scheduled' && referral.scheduled_date && (
                <span className="text-xs text-gray-500">
                  {new Date(referral.scheduled_date).toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                  })}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function WrenchIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
}

export { InstallReferralStatus, InstallReferralList }
export default InstallReferralStatus
