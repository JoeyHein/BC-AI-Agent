import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'
import { savedQuotesApi, ordersApi, historyApi } from '../../api/customerClient'

function CustomerDashboard() {
  const { user, isBCLinked } = useCustomerAuth()

  // Fetch saved quotes
  const { data: savedQuotes, isLoading: quotesLoading } = useQuery({
    queryKey: ['savedQuotes'],
    queryFn: async () => {
      const response = await savedQuotesApi.getAll()
      return response.data
    }
  })

  // Fetch orders
  const { data: orders, isLoading: ordersLoading } = useQuery({
    queryKey: ['orders'],
    queryFn: async () => {
      const response = await ordersApi.getAll()
      return response.data
    },
    enabled: isBCLinked
  })

  // Fetch history summary
  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ['history'],
    queryFn: async () => {
      const response = await historyApi.get()
      return response.data
    },
    enabled: isBCLinked
  })

  const draftQuotes = savedQuotes?.filter(q => !q.is_submitted) || []
  const submittedQuotes = savedQuotes?.filter(q => q.is_submitted) || []
  const activeOrders = orders?.filter(o => !['completed', 'cancelled'].includes(o.status)) || []

  return (
    <div className="space-y-6">
      {/* Welcome section */}
      <div className="bg-white shadow rounded-lg p-6">
        <h1 className="text-2xl font-bold text-gray-900">
          Welcome back, {user?.name || 'Customer'}
        </h1>
        {user?.bc_company_name && (
          <p className="mt-1 text-gray-500">{user.bc_company_name}</p>
        )}
        {!isBCLinked && (
          <div className="mt-4 p-4 bg-yellow-50 rounded-md">
            <p className="text-sm text-yellow-700">
              Your account is not yet linked to our business system. Some features may be limited.
              Please contact support to link your account.
            </p>
          </div>
        )}
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        <Link
          to="saved-quotes/new"
          className="bg-odc-600 hover:bg-odc-700 text-white rounded-lg p-6 shadow flex items-center justify-between"
        >
          <div>
            <h3 className="text-lg font-semibold">Create New Quote</h3>
            <p className="text-blue-100 text-sm mt-1">Configure a new door</p>
          </div>
          <PlusIcon className="h-8 w-8" />
        </Link>

        <Link
          to="saved-quotes"
          className="bg-white hover:bg-gray-50 text-gray-900 rounded-lg p-6 shadow border flex items-center justify-between"
        >
          <div>
            <h3 className="text-lg font-semibold">My Quotes</h3>
            <p className="text-gray-500 text-sm mt-1">{draftQuotes.length} drafts, {submittedQuotes.length} submitted</p>
          </div>
          <DocumentIcon className="h-8 w-8 text-gray-400" />
        </Link>

        <Link
          to="orders"
          className="bg-white hover:bg-gray-50 text-gray-900 rounded-lg p-6 shadow border flex items-center justify-between"
        >
          <div>
            <h3 className="text-lg font-semibold">Track Orders</h3>
            <p className="text-gray-500 text-sm mt-1">{activeOrders.length} active orders</p>
          </div>
          <TruckIcon className="h-8 w-8 text-gray-400" />
        </Link>
      </div>

      {/* Stats cards */}
      {isBCLinked && history && (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          <div className="bg-white rounded-lg shadow p-6">
            <p className="text-sm font-medium text-gray-500">Total Orders</p>
            <p className="mt-2 text-3xl font-bold text-gray-900">{history.total_orders}</p>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <p className="text-sm font-medium text-gray-500">Total Spent</p>
            <p className="mt-2 text-3xl font-bold text-gray-900">
              ${history.total_spent?.toLocaleString('en-US', { minimumFractionDigits: 2 }) || '0.00'}
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <p className="text-sm font-medium text-gray-500">Saved Configurations</p>
            <p className="mt-2 text-3xl font-bold text-gray-900">{savedQuotes?.length || 0}</p>
          </div>
        </div>
      )}

      {/* Recent activity */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Recent drafts */}
        <div className="bg-white shadow rounded-lg">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <h2 className="text-lg font-medium text-gray-900">Recent Drafts</h2>
            <Link to="saved-quotes" className="text-sm text-odc-600 hover:text-odc-500">
              View all
            </Link>
          </div>
          <div className="divide-y divide-gray-200">
            {quotesLoading ? (
              <div className="p-6 text-center text-gray-500">Loading...</div>
            ) : draftQuotes.length === 0 ? (
              <div className="p-6 text-center text-gray-500">
                No draft quotes yet.{' '}
                <Link to="saved-quotes/new" className="text-odc-600 hover:text-odc-500">
                  Create one now
                </Link>
              </div>
            ) : (
              draftQuotes.slice(0, 5).map((quote) => (
                <Link
                  key={quote.id}
                  to={`saved-quotes/${quote.id}`}
                  className="block px-6 py-4 hover:bg-gray-50"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{quote.name || 'Unnamed Quote'}</p>
                      <p className="text-sm text-gray-500">
                        Last updated: {new Date(quote.updated_at || quote.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
                      Draft
                    </span>
                  </div>
                </Link>
              ))
            )}
          </div>
        </div>

        {/* Recent orders */}
        <div className="bg-white shadow rounded-lg">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <h2 className="text-lg font-medium text-gray-900">Recent Orders</h2>
            <Link to="orders" className="text-sm text-odc-600 hover:text-odc-500">
              View all
            </Link>
          </div>
          <div className="divide-y divide-gray-200">
            {!isBCLinked ? (
              <div className="p-6 text-center text-gray-500">
                Link your account to view orders
              </div>
            ) : ordersLoading ? (
              <div className="p-6 text-center text-gray-500">Loading...</div>
            ) : !orders?.length ? (
              <div className="p-6 text-center text-gray-500">No orders yet</div>
            ) : (
              orders.slice(0, 5).map((order) => (
                <Link
                  key={order.id}
                  to={`orders/${order.id}`}
                  className="block px-6 py-4 hover:bg-gray-50"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-900">
                        {order.bc_order_number || `Order #${order.id}`}
                      </p>
                      <p className="text-sm text-gray-500">
                        {new Date(order.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <StatusBadge status={order.status} />
                  </div>
                </Link>
              ))
            )}
          </div>
        </div>
      </div>
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
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {labels[status] || status}
    </span>
  )
}

// Icon components
function PlusIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
    </svg>
  )
}

function DocumentIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
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

export default CustomerDashboard
