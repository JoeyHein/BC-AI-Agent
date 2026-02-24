import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ordersApi, productionApi } from '../api/client'
import { format, parseISO } from 'date-fns'

// BC Sales Order document statuses (from API)
// Note: BC UI "Released" status is a separate release status field not exposed in standard API
// API status reflects document lifecycle: Draft -> Open -> Pending states
const ORDER_STATUSES = [
  { value: 'all', label: 'All Orders', color: 'gray' },
  { value: 'Draft', label: 'Draft', color: 'yellow' },
  { value: 'Open', label: 'Open', color: 'green' },
  { value: 'Pending Approval', label: 'Pending Approval', color: 'orange' },
  { value: 'Pending Prepayment', label: 'Pending Prepayment', color: 'purple' },
]

function OrderManagement() {
  const [statusFilter, setStatusFilter] = useState('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedOrder, setSelectedOrder] = useState(null)
  const [showShipModal, setShowShipModal] = useState(false)
  const queryClient = useQueryClient()

  // Fetch orders
  const { data: ordersData, isLoading, error } = useQuery({
    queryKey: ['adminOrders', statusFilter],
    queryFn: async () => {
      const params = statusFilter !== 'all' ? { status: statusFilter } : {}
      const response = await ordersApi.getAll(params)
      return response.data
    }
  })

  // Update order status mutation
  const updateStatusMutation = useMutation({
    mutationFn: async ({ orderId, status, notes }) => {
      const response = await ordersApi.updateStatus(orderId, status, notes)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminOrders'] })
      setSelectedOrder(null)
    }
  })

  // Ship order mutation
  const shipOrderMutation = useMutation({
    mutationFn: async ({ orderId, shipmentData }) => {
      const response = await ordersApi.createShipment(orderId, shipmentData)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminOrders'] })
      setShowShipModal(false)
      setSelectedOrder(null)
    }
  })

  // Invoice order mutation
  const invoiceOrderMutation = useMutation({
    mutationFn: async (orderId) => {
      const response = await ordersApi.createInvoice(orderId)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminOrders'] })
    }
  })

  // Filter orders by search term
  const filteredOrders = ordersData?.orders?.filter(order => {
    if (!searchTerm) return true
    const search = searchTerm.toLowerCase()
    return (
      order.order_number?.toLowerCase().includes(search) ||
      order.customer_name?.toLowerCase().includes(search) ||
      order.bc_order_number?.toLowerCase().includes(search)
    )
  }) || []

  // Calculate stats from BC statuses
  const stats = {
    total: ordersData?.orders?.length || 0,
    draft: ordersData?.orders?.filter(o => o.status === 'Draft').length || 0,
    open: ordersData?.orders?.filter(o => o.status === 'Open').length || 0,
    released: ordersData?.orders?.filter(o => o.status === 'Released').length || 0,
  }

  const getStatusColor = (status) => {
    // Map BC status to colors
    const statusColors = {
      'Draft': 'bg-yellow-100 text-yellow-800',
      'Open': 'bg-blue-100 text-blue-800',
      'Released': 'bg-green-100 text-green-800',
      'Pending Approval': 'bg-orange-100 text-orange-800',
      'Pending Prepayment': 'bg-odc-100 text-odc-800',
    }
    return statusColors[status] || 'bg-gray-100 text-gray-800'
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Order Management</h1>
          <p className="mt-1 text-sm text-gray-500">Track and manage all customer orders</p>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Orders"
          value={stats.total}
          icon={<ClipboardIcon />}
          color="blue"
        />
        <StatCard
          title="Draft"
          value={stats.draft}
          icon={<ClockIcon />}
          color="yellow"
        />
        <StatCard
          title="Open"
          value={stats.open}
          icon={<CogIcon />}
          color="blue"
        />
        <StatCard
          title="Released"
          value={stats.released}
          icon={<TruckIcon />}
          color="green"
        />
      </div>

      {/* Data Source Indicator */}
      {ordersData?.source && (
        <div className="text-xs text-gray-500 flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-green-500"></span>
          Live data from Business Central
        </div>
      )}

      {/* Filters */}
      <div className="bg-white shadow rounded-lg p-4">
        <div className="flex flex-col sm:flex-row gap-4">
          {/* Search */}
          <div className="flex-1">
            <div className="relative">
              <input
                type="text"
                placeholder="Search by order number, customer..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-md focus:ring-odc-500 focus:border-odc-500"
              />
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <svg className="h-5 w-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </div>
            </div>
          </div>

          {/* Status Filter */}
          <div className="flex flex-wrap gap-2">
            {ORDER_STATUSES.slice(0, 5).map(status => (
              <button
                key={status.value}
                onClick={() => setStatusFilter(status.value)}
                className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
                  statusFilter === status.value
                    ? 'bg-odc-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {status.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Orders Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="flex justify-center items-center h-64">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-odc-600"></div>
          </div>
        ) : error ? (
          <div className="p-6 text-center text-red-600">
            Error loading orders: {error.message}
          </div>
        ) : filteredOrders.length === 0 ? (
          <div className="p-12 text-center">
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">No orders found</h3>
            <p className="mt-1 text-sm text-gray-500">
              {statusFilter !== 'all' ? 'Try changing the status filter' : 'No orders have been created yet'}
            </p>
          </div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Order</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Customer</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Total</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {filteredOrders.map((order) => (
                <tr key={order.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm font-medium text-gray-900">
                      {order.order_number || order.bc_order_number || `#${order.id}`}
                    </div>
                    {order.bc_order_number && order.order_number && (
                      <div className="text-xs text-gray-500">BC: {order.bc_order_number}</div>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-gray-900">{order.customer_name || 'N/A'}</div>
                    <div className="text-xs text-gray-500">{order.customer_email}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(order.status)}`}>
                      {order.status?.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {order.created_at ? format(parseISO(order.created_at), 'MMM d, yyyy') : '-'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    ${order.total_amount?.toLocaleString() || '0.00'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button
                      onClick={() => setSelectedOrder(order)}
                      className="text-odc-600 hover:text-odc-900"
                    >
                      Manage
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Order Detail Modal */}
      {selectedOrder && (
        <OrderDetailModal
          order={selectedOrder}
          onClose={() => setSelectedOrder(null)}
          onUpdateStatus={(status, notes) => updateStatusMutation.mutate({
            orderId: selectedOrder.id,
            status,
            notes
          })}
          onShip={() => setShowShipModal(true)}
          onInvoice={() => invoiceOrderMutation.mutate(selectedOrder.id)}
          isUpdating={updateStatusMutation.isPending}
          isInvoicing={invoiceOrderMutation.isPending}
        />
      )}

      {/* Ship Modal */}
      {showShipModal && selectedOrder && (
        <ShipOrderModal
          order={selectedOrder}
          onClose={() => setShowShipModal(false)}
          onShip={(shipmentData) => shipOrderMutation.mutate({
            orderId: selectedOrder.id,
            shipmentData
          })}
          isLoading={shipOrderMutation.isPending}
        />
      )}
    </div>
  )
}

function StatCard({ title, value, icon, color }) {
  const colors = {
    blue: 'bg-blue-500',
    yellow: 'bg-yellow-500',
    purple: 'bg-purple-500',
    green: 'bg-green-500',
  }

  return (
    <div className="bg-white shadow rounded-lg p-5">
      <div className="flex items-center">
        <div className={`${colors[color]} rounded-md p-3 text-white`}>
          {icon}
        </div>
        <div className="ml-5">
          <dt className="text-sm font-medium text-gray-500 truncate">{title}</dt>
          <dd className="text-2xl font-semibold text-gray-900">{value}</dd>
        </div>
      </div>
    </div>
  )
}

function OrderDetailModal({ order, onClose, onUpdateStatus, onShip, onInvoice, isUpdating, isInvoicing }) {
  const [newStatus, setNewStatus] = useState(order.status)
  const [notes, setNotes] = useState('')

  const availableActions = getAvailableActions(order.status)

  return (
    <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto m-4">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-medium text-gray-900">
              Order {order.order_number || order.bc_order_number || `#${order.id}`}
            </h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className="p-6 space-y-6">
          {/* Order Info */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-500">Customer</label>
              <p className="mt-1 text-sm text-gray-900">{order.customer_name || 'N/A'}</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-500">Status</label>
              <p className="mt-1">
                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                  order.status === 'completed' ? 'bg-green-100 text-green-800' :
                  order.status === 'in_production' ? 'bg-purple-100 text-purple-800' :
                  'bg-blue-100 text-blue-800'
                }`}>
                  {order.status?.replace('_', ' ')}
                </span>
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-500">Created</label>
              <p className="mt-1 text-sm text-gray-900">
                {order.created_at ? format(parseISO(order.created_at), 'MMM d, yyyy h:mm a') : '-'}
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-500">Total</label>
              <p className="mt-1 text-sm text-gray-900">${order.total_amount?.toLocaleString() || '0.00'}</p>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="border-t border-gray-200 pt-4">
            <label className="block text-sm font-medium text-gray-700 mb-3">Quick Actions</label>
            <div className="flex flex-wrap gap-2">
              {availableActions.includes('confirm') && (
                <button
                  onClick={() => onUpdateStatus('confirmed', 'Order confirmed')}
                  disabled={isUpdating}
                  className="px-3 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  Confirm Order
                </button>
              )}
              {availableActions.includes('production') && (
                <button
                  onClick={() => onUpdateStatus('in_production', 'Sent to production')}
                  disabled={isUpdating}
                  className="px-3 py-2 bg-purple-600 text-white rounded-md text-sm hover:bg-purple-700 disabled:opacity-50"
                >
                  Start Production
                </button>
              )}
              {availableActions.includes('ready') && (
                <button
                  onClick={() => onUpdateStatus('ready_to_ship', 'Production complete')}
                  disabled={isUpdating}
                  className="px-3 py-2 bg-odc-600 text-white rounded-md text-sm hover:bg-odc-700 disabled:opacity-50"
                >
                  Mark Ready to Ship
                </button>
              )}
              {availableActions.includes('ship') && (
                <button
                  onClick={onShip}
                  disabled={isUpdating}
                  className="px-3 py-2 bg-cyan-600 text-white rounded-md text-sm hover:bg-cyan-700 disabled:opacity-50"
                >
                  Ship Order
                </button>
              )}
              {availableActions.includes('invoice') && (
                <button
                  onClick={onInvoice}
                  disabled={isInvoicing}
                  className="px-3 py-2 bg-green-600 text-white rounded-md text-sm hover:bg-green-700 disabled:opacity-50"
                >
                  {isInvoicing ? 'Creating...' : 'Create Invoice'}
                </button>
              )}
            </div>
          </div>

          {/* Status Update */}
          <div className="border-t border-gray-200 pt-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">Update Status</label>
            <div className="flex gap-3">
              <select
                value={newStatus}
                onChange={(e) => setNewStatus(e.target.value)}
                className="flex-1 border-gray-300 rounded-md shadow-sm focus:ring-odc-500 focus:border-odc-500"
              >
                {ORDER_STATUSES.filter(s => s.value !== 'all').map(status => (
                  <option key={status.value} value={status.value}>{status.label}</option>
                ))}
              </select>
              <button
                onClick={() => onUpdateStatus(newStatus, notes)}
                disabled={isUpdating || newStatus === order.status}
                className="px-4 py-2 bg-odc-600 text-white rounded-md text-sm hover:bg-odc-700 disabled:opacity-50"
              >
                {isUpdating ? 'Updating...' : 'Update'}
              </button>
            </div>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add notes (optional)"
              className="mt-2 w-full border-gray-300 rounded-md shadow-sm focus:ring-odc-500 focus:border-odc-500"
              rows={2}
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
          <button
            onClick={onClose}
            className="w-full px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

function ShipOrderModal({ order, onClose, onShip, isLoading }) {
  const [shipmentData, setShipmentData] = useState({
    carrier: 'FedEx',
    tracking_number: '',
    ship_date: format(new Date(), 'yyyy-MM-dd'),
    notes: ''
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    onShip(shipmentData)
  }

  return (
    <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full m-4">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-medium text-gray-900">Ship Order</h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Carrier</label>
            <select
              value={shipmentData.carrier}
              onChange={(e) => setShipmentData({ ...shipmentData, carrier: e.target.value })}
              className="w-full border-gray-300 rounded-md shadow-sm focus:ring-odc-500 focus:border-odc-500"
            >
              <option value="FedEx">FedEx</option>
              <option value="UPS">UPS</option>
              <option value="USPS">USPS</option>
              <option value="DHL">DHL</option>
              <option value="Purolator">Purolator</option>
              <option value="Canada Post">Canada Post</option>
              <option value="Other">Other</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Tracking Number</label>
            <input
              type="text"
              value={shipmentData.tracking_number}
              onChange={(e) => setShipmentData({ ...shipmentData, tracking_number: e.target.value })}
              placeholder="Enter tracking number"
              className="w-full border-gray-300 rounded-md shadow-sm focus:ring-odc-500 focus:border-odc-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Ship Date</label>
            <input
              type="date"
              value={shipmentData.ship_date}
              onChange={(e) => setShipmentData({ ...shipmentData, ship_date: e.target.value })}
              className="w-full border-gray-300 rounded-md shadow-sm focus:ring-odc-500 focus:border-odc-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Notes</label>
            <textarea
              value={shipmentData.notes}
              onChange={(e) => setShipmentData({ ...shipmentData, notes: e.target.value })}
              placeholder="Optional shipping notes"
              rows={2}
              className="w-full border-gray-300 rounded-md shadow-sm focus:ring-odc-500 focus:border-odc-500"
            />
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="flex-1 px-4 py-2 bg-odc-600 text-white rounded-md text-sm font-medium hover:bg-odc-700 disabled:opacity-50"
            >
              {isLoading ? 'Shipping...' : 'Ship Order'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function getAvailableActions(status) {
  const actions = {
    pending: ['confirm'],
    confirmed: ['production'],
    in_production: ['ready'],
    ready_to_ship: ['ship'],
    shipped: ['invoice'],
    invoiced: [],
    completed: [],
  }
  return actions[status] || []
}

// Icons
function ClipboardIcon() {
  return (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
    </svg>
  )
}

function ClockIcon() {
  return (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

function CogIcon() {
  return (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
}

function TruckIcon() {
  return (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path d="M9 17a2 2 0 11-4 0 2 2 0 014 0zM19 17a2 2 0 11-4 0 2 2 0 014 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16V6a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h1m8-1a1 1 0 01-1 1H9m4-1V8a1 1 0 011-1h2.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V16a1 1 0 01-1 1h-1m-6-1a1 1 0 001 1h1M5 17a2 2 0 104 0m-4 0a2 2 0 114 0m6 0a2 2 0 104 0m-4 0a2 2 0 114 0" />
    </svg>
  )
}

export default OrderManagement
