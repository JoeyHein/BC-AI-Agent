import { Link, useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ordersApi } from '../../api/customerClient'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'

function OrderDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { isBCLinked } = useCustomerAuth()

  const { data, isLoading, error } = useQuery({
    queryKey: ['order', id],
    queryFn: async () => {
      const response = await ordersApi.get(id)
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
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="bg-red-50 p-4 rounded-md">
        <p className="text-red-700">Failed to load order details. Please try again.</p>
        <button
          onClick={() => navigate('/orders')}
          className="mt-4 text-blue-600 hover:text-blue-500"
        >
          Back to orders
        </button>
      </div>
    )
  }

  const { order, shipments, invoices } = data

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <button
            onClick={() => navigate('/orders')}
            className="text-sm text-gray-500 hover:text-gray-700 flex items-center"
          >
            <ArrowLeftIcon className="h-4 w-4 mr-1" />
            Back to orders
          </button>
          <h1 className="mt-2 text-2xl font-bold text-gray-900">
            Order {order.bc_order_number || `#${order.id}`}
          </h1>
        </div>
        <Link
          to="tracking"
          className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700"
        >
          <TruckIcon className="h-5 w-5 mr-2" />
          Track Order
        </Link>
      </div>

      {/* Order summary */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Order Summary</h2>
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <dt className="text-sm text-gray-500">Status</dt>
            <dd className="mt-1">
              <StatusBadge status={order.status} />
            </dd>
          </div>
          <div>
            <dt className="text-sm text-gray-500">Order Date</dt>
            <dd className="mt-1 text-sm font-medium text-gray-900">
              {new Date(order.created_at).toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'long',
                day: 'numeric'
              })}
            </dd>
          </div>
          {order.total_amount && (
            <div>
              <dt className="text-sm text-gray-500">Total Amount</dt>
              <dd className="mt-1 text-sm font-medium text-gray-900">
                ${order.total_amount.toLocaleString('en-US', { minimumFractionDigits: 2 })} {order.currency || 'CAD'}
              </dd>
            </div>
          )}
          {order.bc_order_id && (
            <div>
              <dt className="text-sm text-gray-500">BC Reference</dt>
              <dd className="mt-1 text-sm font-medium text-gray-900">
                {order.bc_order_number}
              </dd>
            </div>
          )}
        </dl>

        {/* Timeline */}
        <div className="mt-6 pt-6 border-t border-gray-200">
          <h3 className="text-sm font-medium text-gray-900 mb-4">Order Timeline</h3>
          <div className="space-y-4">
            <TimelineItem
              title="Order Placed"
              date={order.created_at}
              completed={true}
            />
            <TimelineItem
              title="Order Confirmed"
              date={order.confirmed_at}
              completed={!!order.confirmed_at}
            />
            <TimelineItem
              title="In Production"
              date={order.production_started_at}
              completed={!!order.production_started_at}
            />
            <TimelineItem
              title="Shipped"
              date={order.shipped_at}
              completed={!!order.shipped_at}
            />
            <TimelineItem
              title="Invoiced"
              date={order.invoiced_at}
              completed={!!order.invoiced_at}
              isLast
            />
          </div>
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
                      {shipment.shipment_number || `Shipment #${shipment.id}`}
                    </p>
                    {shipment.shipped_date && (
                      <p className="text-sm text-gray-500">
                        Shipped: {new Date(shipment.shipped_date).toLocaleDateString()}
                      </p>
                    )}
                  </div>
                  {shipment.tracking_number && (
                    <div className="text-right">
                      <p className="text-sm text-gray-500">Tracking Number</p>
                      <p className="font-medium text-blue-600">{shipment.tracking_number}</p>
                      {shipment.carrier && (
                        <p className="text-xs text-gray-500">{shipment.carrier}</p>
                      )}
                    </div>
                  )}
                </div>
                {shipment.ship_to_name && (
                  <p className="mt-2 text-sm text-gray-500">
                    Ship to: {shipment.ship_to_name}
                  </p>
                )}
                {shipment.delivered_at && (
                  <p className="mt-2 text-sm text-green-600">
                    Delivered: {new Date(shipment.delivered_at).toLocaleDateString()}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Invoices */}
      {invoices && invoices.length > 0 && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Invoices</h2>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Invoice
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Amount
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Due Date
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Paid
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {invoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {invoice.invoice_number || `#${invoice.id}`}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <InvoiceStatusBadge status={invoice.status} />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                      {invoice.total_amount
                        ? `$${invoice.total_amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
                        : '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {invoice.due_date
                        ? new Date(invoice.due_date).toLocaleDateString()
                        : '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {invoice.amount_paid
                        ? `$${invoice.amount_paid.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
                        : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }) {
  const colors = {
    pending: 'bg-gray-100 text-gray-800',
    confirmed: 'bg-blue-100 text-blue-800',
    in_production: 'bg-yellow-100 text-yellow-800',
    ready_to_ship: 'bg-purple-100 text-purple-800',
    shipped: 'bg-indigo-100 text-indigo-800',
    invoiced: 'bg-green-100 text-green-800',
    completed: 'bg-green-100 text-green-800',
    cancelled: 'bg-red-100 text-red-800'
  }

  const labels = {
    pending: 'Pending',
    confirmed: 'Confirmed',
    in_production: 'In Production',
    ready_to_ship: 'Ready to Ship',
    shipped: 'Shipped',
    invoiced: 'Invoiced',
    completed: 'Completed',
    cancelled: 'Cancelled'
  }

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {labels[status] || status}
    </span>
  )
}

function InvoiceStatusBadge({ status }) {
  const colors = {
    draft: 'bg-gray-100 text-gray-800',
    posted: 'bg-blue-100 text-blue-800',
    paid: 'bg-green-100 text-green-800',
    partially_paid: 'bg-yellow-100 text-yellow-800',
    overdue: 'bg-red-100 text-red-800',
    cancelled: 'bg-red-100 text-red-800'
  }

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium capitalize ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {status.replace('_', ' ')}
    </span>
  )
}

function TimelineItem({ title, date, completed, isLast }) {
  return (
    <div className="flex">
      <div className="flex flex-col items-center">
        <div className={`w-4 h-4 rounded-full flex items-center justify-center ${
          completed ? 'bg-green-500' : 'bg-gray-300'
        }`}>
          {completed && (
            <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
          )}
        </div>
        {!isLast && (
          <div className={`w-0.5 h-8 ${completed ? 'bg-green-500' : 'bg-gray-300'}`} />
        )}
      </div>
      <div className="ml-4 -mt-1">
        <p className={`text-sm font-medium ${completed ? 'text-gray-900' : 'text-gray-500'}`}>
          {title}
        </p>
        {date && (
          <p className="text-xs text-gray-500">
            {new Date(date).toLocaleDateString('en-US', {
              year: 'numeric',
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit'
            })}
          </p>
        )}
      </div>
    </div>
  )
}

function ArrowLeftIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
    </svg>
  )
}

function TruckIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path d="M9 17a2 2 0 11-4 0 2 2 0 014 0zM19 17a2 2 0 11-4 0 2 2 0 014 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16V6a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h1m8-1a1 1 0 01-1 1H9m4-1V8a1 1 0 011-1h2.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V16a1 1 0 01-1 1h-1m-6-1a1 1 0 001 1h1M5 17a2 2 0 104 0m-4 0a2 2 0 114 0m6 0a2 2 0 104 0m-4 0a2 2 0 114 0" />
    </svg>
  )
}

export default OrderDetail
