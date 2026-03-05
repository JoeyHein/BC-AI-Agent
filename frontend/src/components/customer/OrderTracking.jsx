import { Link, useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ordersApi } from '../../api/customerClient'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'

function OrderTracking() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { isBCLinked } = useCustomerAuth()

  const { data, isLoading, error } = useQuery({
    queryKey: ['orderTracking', id],
    queryFn: async () => {
      const response = await ordersApi.getTracking(id)
      return response.data
    },
    enabled: isBCLinked
  })

  if (!isBCLinked) {
    return (
      <div className="bg-yellow-50 p-6 rounded-lg text-center">
        <h2 className="text-lg font-medium text-yellow-800">Account Not Linked</h2>
        <p className="mt-2 text-yellow-700">
          Your account is not yet linked to our business system.
        </p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="bg-red-50 p-4 rounded-md">
        <p className="text-red-700">Failed to load tracking information. Please try again.</p>
        <button
          onClick={() => navigate('/orders')}
          className="mt-4 text-odc-600 hover:text-odc-500"
        >
          Back to orders
        </button>
      </div>
    )
  }

  const { order_number, current_status, timeline, shipments } = data

  // Find current step index and calculate progress percentage
  const completedSteps = timeline.filter(t => t.status === 'completed').length
  const currentStepIndex = timeline.findIndex(t => t.status === 'current')
  const progressPercent = currentStepIndex >= 0
    ? ((currentStepIndex + 0.5) / timeline.length) * 100
    : (completedSteps / timeline.length) * 100

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <button
            onClick={() => navigate(`/orders/${id}`)}
            className="text-sm text-gray-500 hover:text-gray-700 flex items-center"
          >
            <ArrowLeftIcon className="h-4 w-4 mr-1" />
            Back to order details
          </button>
          <h1 className="mt-2 text-2xl font-bold text-gray-900">
            Track Order {order_number || `${id.substring(0, 8)}...`}
          </h1>
        </div>
        <StatusBadge status={current_status} />
      </div>

      {/* Visual tracking progress */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-6">Order Progress</h2>

        {/* Progress bar */}
        <div className="relative">
          <div className="overflow-hidden h-3 text-xs flex rounded-full bg-gray-200">
            <div
              style={{ width: `${progressPercent}%` }}
              className="shadow-none flex flex-col text-center whitespace-nowrap text-white justify-center bg-gradient-to-r from-odc-500 to-odc-600 rounded-full transition-all duration-1000 ease-out"
            />
          </div>

          {/* Steps */}
          <div className="flex justify-between mt-4">
            {timeline.map((step, index) => (
              <div
                key={step.event_type}
                className={`flex flex-col items-center ${index === 0 ? 'items-start' : index === timeline.length - 1 ? 'items-end' : ''}`}
              >
                <div className="relative">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-medium ${
                    step.status === 'completed'
                      ? 'bg-green-500 text-white'
                      : step.status === 'current'
                      ? 'bg-odc-500 text-white'
                      : 'bg-gray-200 text-gray-500'
                  }`}>
                    {step.status === 'completed' ? (
                      <CheckIcon className="h-5 w-5" />
                    ) : (
                      index + 1
                    )}
                  </div>
                  {step.status === 'current' && (
                    <span className="absolute inset-0 rounded-full animate-ping bg-odc-400 opacity-30" />
                  )}
                </div>
                <p className={`mt-2 text-xs font-medium text-center ${
                  step.status === 'completed' || step.status === 'current'
                    ? 'text-gray-900'
                    : 'text-gray-400'
                }`}>
                  {step.description}
                </p>
                {step.timestamp && (
                  <p className="text-xs text-gray-500">
                    {new Date(step.timestamp).toLocaleDateString()}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Timeline detail */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Timeline</h2>
        <div className="flow-root">
          <ul className="-mb-8">
            {timeline.map((event, eventIdx) => (
              <li key={event.event_type}>
                <div className="relative pb-8">
                  {eventIdx !== timeline.length - 1 && (
                    <span
                      className={`absolute top-4 left-4 -ml-px h-full w-0.5 ${
                        event.status === 'completed' ? 'bg-green-500' : 'bg-gray-200'
                      }`}
                      aria-hidden="true"
                    />
                  )}
                  <div className="relative flex space-x-3">
                    <div>
                      <span className={`h-8 w-8 rounded-full flex items-center justify-center ring-8 ring-white ${
                        event.status === 'completed'
                          ? 'bg-green-500'
                          : event.status === 'current'
                          ? 'bg-odc-500'
                          : 'bg-gray-200'
                      }`}>
                        {event.status === 'completed' ? (
                          <CheckIcon className="h-5 w-5 text-white" />
                        ) : event.status === 'current' ? (
                          <ClockIcon className="h-5 w-5 text-white" />
                        ) : (
                          <div className="h-2 w-2 rounded-full bg-gray-400" />
                        )}
                      </span>
                      {event.status === 'current' && (
                        <span className="absolute top-0 left-0 h-8 w-8 rounded-full animate-ping bg-odc-400 opacity-20" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1 pt-1.5 flex justify-between space-x-4">
                      <div>
                        <p className={`text-sm ${
                          event.status === 'pending' ? 'text-gray-400' : 'text-gray-900'
                        }`}>
                          {event.description}
                        </p>
                        {event.status === 'current' && (
                          <p className="mt-1 text-xs text-odc-600">
                            In progress...
                          </p>
                        )}
                      </div>
                      {event.timestamp && (
                        <div className="text-right text-sm whitespace-nowrap text-gray-500">
                          <time dateTime={event.timestamp}>
                            {new Date(event.timestamp).toLocaleDateString('en-US', {
                              month: 'short',
                              day: 'numeric'
                            })}
                          </time>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Shipments */}
      {shipments && shipments.length > 0 && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Shipments</h2>
          <div className="space-y-4">
            {shipments.map((shipment) => (
              <div key={shipment.id} className="border border-gray-200 rounded-lg p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-gray-900">
                      {shipment.number ? `Shipment ${shipment.number}` : 'Shipment'}
                    </p>
                    {shipment.shipment_date && (
                      <p className="text-sm text-gray-500">
                        Shipped: {new Date(shipment.shipment_date).toLocaleDateString()}
                      </p>
                    )}
                  </div>
                  {shipment.ship_to_name && (
                    <p className="text-sm text-gray-500">
                      Ship to: {shipment.ship_to_name}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }) {
  const colors = {
    draft: 'bg-gray-100 text-gray-800',
    open: 'bg-blue-100 text-blue-800',
    released: 'bg-green-100 text-green-800',
    pending_approval: 'bg-yellow-100 text-yellow-800',
    pending_prepayment: 'bg-yellow-100 text-yellow-800',
    completed: 'bg-green-100 text-green-800',
    cancelled: 'bg-red-100 text-red-800',
  }

  const labels = {
    draft: 'Draft',
    open: 'Open',
    released: 'Released',
    pending_approval: 'Pending Approval',
    pending_prepayment: 'Pending Prepayment',
    completed: 'Completed',
    cancelled: 'Cancelled',
  }

  return (
    <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {labels[status] || status}
    </span>
  )
}

function ArrowLeftIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
    </svg>
  )
}

function CheckIcon({ className }) {
  return (
    <svg className={className} fill="currentColor" viewBox="0 0 20 20">
      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
    </svg>
  )
}

function ClockIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

export default OrderTracking
