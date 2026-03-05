import { useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ordersApi } from '../../api/customerClient'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'

function OrderDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { isBCLinked } = useCustomerAuth()
  const [downloadingPdf, setDownloadingPdf] = useState(false)

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
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="bg-red-50 p-4 rounded-md">
        <p className="text-red-700">Failed to load order details. Please try again.</p>
        <button
          onClick={() => navigate('/orders')}
          className="mt-4 text-odc-600 hover:text-odc-500"
        >
          Back to orders
        </button>
      </div>
    )
  }

  const { order, lines, shipments, invoices } = data

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
            Order {order.number || `${order.id.substring(0, 8)}...`}
          </h1>
        </div>
        <div className="flex gap-3">
          <button
            onClick={async () => {
              setDownloadingPdf(true)
              try {
                const response = await ordersApi.getAcknowledgementPdf(id)
                const url = window.URL.createObjectURL(new Blob([response.data]))
                const link = document.createElement('a')
                link.href = url
                link.setAttribute('download', `Order_Acknowledgement_${order.number || id}.pdf`)
                document.body.appendChild(link)
                link.click()
                link.remove()
                window.URL.revokeObjectURL(url)
              } catch (err) {
                alert('Failed to download acknowledgement PDF')
              } finally {
                setDownloadingPdf(false)
              }
            }}
            disabled={downloadingPdf}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
          >
            <DownloadIcon className="h-5 w-5 mr-2" />
            {downloadingPdf ? 'Downloading...' : 'Download Acknowledgement'}
          </button>
          <Link
            to="tracking"
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700"
          >
            <TruckIcon className="h-5 w-5 mr-2" />
            Track Order
          </Link>
        </div>
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
          {order.order_date && (
            <div>
              <dt className="text-sm text-gray-500">Order Date</dt>
              <dd className="mt-1 text-sm font-medium text-gray-900">
                {new Date(order.order_date).toLocaleDateString('en-US', {
                  year: 'numeric',
                  month: 'long',
                  day: 'numeric'
                })}
              </dd>
            </div>
          )}
          {order.total_amount != null && (
            <div>
              <dt className="text-sm text-gray-500">Total Amount</dt>
              <dd className="mt-1 text-sm font-medium text-gray-900">
                ${order.total_amount.toLocaleString('en-US', { minimumFractionDigits: 2 })} {order.currency || 'CAD'}
              </dd>
            </div>
          )}
          {order.requested_delivery_date && order.requested_delivery_date !== '0001-01-01' && (
            <div>
              <dt className="text-sm text-gray-500">Requested Delivery</dt>
              <dd className="mt-1 text-sm font-medium text-gray-900">
                {new Date(order.requested_delivery_date).toLocaleDateString('en-US', {
                  year: 'numeric',
                  month: 'long',
                  day: 'numeric'
                })}
              </dd>
            </div>
          )}
        </dl>
      </div>

      {/* Order Lines */}
      {lines && lines.length > 0 && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Order Lines</h2>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Item
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Description
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Qty
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Unit Price
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Amount
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {lines.map((line, idx) => (
                  <tr key={idx}>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {line.item_number || '-'}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900">
                      {line.description || '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                      {line.quantity ?? '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                      {line.unit_price != null
                        ? `$${line.unit_price.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
                        : '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                      {line.line_amount != null
                        ? `$${line.line_amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
                        : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
                      {shipment.number ? `Shipment ${shipment.number}` : `Shipment`}
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
                    Date
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Amount
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Due Date
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {invoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {invoice.number || '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {invoice.invoice_date
                        ? new Date(invoice.invoice_date).toLocaleDateString()
                        : '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                      {invoice.total_amount != null
                        ? `$${invoice.total_amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
                        : '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {invoice.due_date
                        ? new Date(invoice.due_date).toLocaleDateString()
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
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
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

function DownloadIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
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
