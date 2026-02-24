import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ordersApi } from '../../api/customerClient'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'

function MyOrders() {
  const [filter, setFilter] = useState('all')
  const { isBCLinked } = useCustomerAuth()

  const { data: orders, isLoading, error } = useQuery({
    queryKey: ['orders'],
    queryFn: async () => {
      const response = await ordersApi.getAll()
      return response.data
    },
    enabled: isBCLinked
  })

  const filteredOrders = orders?.filter(order => {
    if (filter === 'active') return !['completed', 'cancelled'].includes(order.status)
    if (filter === 'completed') return order.status === 'completed'
    return true
  }) || []

  if (!isBCLinked) {
    return (
      <div className="bg-yellow-50 p-6 rounded-lg text-center">
        <h2 className="text-lg font-medium text-yellow-800">Account Not Linked</h2>
        <p className="mt-2 text-yellow-700">
          Your account is not yet linked to our business system.
          Please contact support to link your account and view your orders.
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

  if (error) {
    return (
      <div className="bg-red-50 p-4 rounded-md">
        <p className="text-red-700">Failed to load orders. Please try again.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">My Orders</h1>
        <p className="mt-1 text-sm text-gray-500">
          Track your orders and view their status
        </p>
      </div>

      {/* Filter tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          {[
            { key: 'all', label: 'All Orders', count: orders?.length || 0 },
            { key: 'active', label: 'Active', count: orders?.filter(o => !['completed', 'cancelled'].includes(o.status)).length || 0 },
            { key: 'completed', label: 'Completed', count: orders?.filter(o => o.status === 'completed').length || 0 },
          ].map((tab) => (
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

      {/* Orders list */}
      {filteredOrders.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <TruckIcon className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-2 text-sm font-medium text-gray-900">No orders</h3>
          <p className="mt-1 text-sm text-gray-500">
            {filter === 'all'
              ? "You don't have any orders yet."
              : `No ${filter} orders found.`}
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredOrders.map((order) => (
            <div key={order.id} className="bg-white shadow rounded-lg overflow-hidden">
              <div className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-medium text-gray-900">
                      {order.bc_order_number || `Order #${order.id}`}
                    </h3>
                    <p className="mt-1 text-sm text-gray-500">
                      Placed on {new Date(order.created_at).toLocaleDateString('en-US', {
                        year: 'numeric',
                        month: 'long',
                        day: 'numeric'
                      })}
                    </p>
                  </div>
                  <StatusBadge status={order.status} />
                </div>

                {order.total_amount && (
                  <p className="mt-4 text-sm text-gray-700">
                    Total: <span className="font-medium">
                      ${order.total_amount.toLocaleString('en-US', { minimumFractionDigits: 2 })} {order.currency || 'CAD'}
                    </span>
                  </p>
                )}

                {/* Status timeline preview */}
                <div className="mt-4 flex items-center space-x-4 text-xs text-gray-500">
                  <TimelineStep
                    label="Ordered"
                    completed={true}
                    date={order.created_at}
                  />
                  <TimelineStep
                    label="Confirmed"
                    completed={!!order.confirmed_at}
                    date={order.confirmed_at}
                  />
                  <TimelineStep
                    label="Shipped"
                    completed={!!order.shipped_at}
                    date={order.shipped_at}
                  />
                  <TimelineStep
                    label="Invoiced"
                    completed={!!order.invoiced_at}
                    date={order.invoiced_at}
                  />
                </div>

                <div className="mt-6 flex items-center space-x-4">
                  <Link
                    to={`${order.id}`}
                    className="text-sm font-medium text-odc-600 hover:text-odc-500"
                  >
                    View Details
                  </Link>
                  <Link
                    to={`${order.id}/tracking`}
                    className="text-sm font-medium text-odc-600 hover:text-odc-500"
                  >
                    Track Order
                  </Link>
                </div>
              </div>
            </div>
          ))}
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
    shipped: 'bg-cyan-100 text-cyan-800',
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
    <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {labels[status] || status}
    </span>
  )
}

function TimelineStep({ label, completed, date }) {
  return (
    <div className="flex items-center">
      <div className={`w-3 h-3 rounded-full ${completed ? 'bg-green-500' : 'bg-gray-300'}`} />
      <span className={`ml-2 ${completed ? 'text-gray-900' : 'text-gray-400'}`}>
        {label}
        {completed && date && (
          <span className="ml-1 text-gray-500">
            ({new Date(date).toLocaleDateString()})
          </span>
        )}
      </span>
    </div>
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

export default MyOrders
