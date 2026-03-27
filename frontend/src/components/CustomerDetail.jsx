import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { metricsApi, customersApi } from '../api/client'

function fmt$(val) {
  if (val >= 1_000_000) return `$${(val / 1_000_000).toFixed(1)}M`
  if (val >= 1_000) return `$${(val / 1_000).toFixed(1)}K`
  return `$${Math.round(val).toLocaleString()}`
}

function DeltaBadge({ value }) {
  if (value == null || value === 0) return <span className="text-xs text-gray-400">—</span>
  const up = value > 0
  return (
    <span className={`text-xs font-medium ${up ? 'text-green-600' : 'text-red-600'}`}>
      {up ? '\u25B2' : '\u25BC'} {Math.abs(value).toFixed(1)}%
    </span>
  )
}

function KPICard({ title, value, delta, sub, loading }) {
  if (loading) {
    return (
      <div className="bg-white shadow rounded-lg p-4 animate-pulse">
        <div className="h-3 bg-gray-200 rounded w-20 mb-2" />
        <div className="h-6 bg-gray-200 rounded w-28 mb-1" />
        <div className="h-3 bg-gray-200 rounded w-16" />
      </div>
    )
  }
  return (
    <div className="bg-white shadow rounded-lg p-4">
      <p className="text-xs text-gray-500">{title}</p>
      <p className="mt-1 text-xl font-bold text-gray-900">{value}</p>
      <div className="mt-0.5 flex items-center gap-2">
        {delta != null && <DeltaBadge value={delta} />}
        {sub && <span className="text-xs text-gray-400">{sub}</span>}
      </div>
    </div>
  )
}

function CustomerDetail() {
  const { id } = useParams()

  // Fetch local customer data (for tier, linked BC number, etc.)
  const { data: customerData } = useQuery({
    queryKey: ['customer', id],
    queryFn: async () => {
      const r = await customersApi.getCustomer(id)
      return r.data
    },
    staleTime: 60_000,
  })

  const bcNumber = customerData?.bc_customer_number || customerData?.bc_number || id

  // Fetch BC metrics
  const { data: metrics, isLoading, error } = useQuery({
    queryKey: ['metrics', 'customer', bcNumber],
    queryFn: async () => {
      const r = await metricsApi.getCustomer(bcNumber)
      return r.data.data
    },
    enabled: !!bcNumber,
    staleTime: 120_000,
  })

  const d = metrics || {}
  const profile = d.profile || {}

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center text-sm text-gray-500">
        <Link to="/customers" className="hover:text-odc-600">Customers</Link>
        <span className="mx-2">/</span>
        <span className="text-gray-900 font-medium">{profile.name || bcNumber}</span>
      </div>

      {/* Profile header */}
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{profile.name || 'Loading...'}</h1>
            <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
              <span>#{profile.number}</span>
              {profile.city && <span>{profile.city}{profile.state ? `, ${profile.state}` : ''}</span>}
              {profile.salesperson && <span>Rep: {profile.salesperson}</span>}
              {customerData?.pricing_tier && (
                <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${
                  { gold: 'bg-yellow-100 text-yellow-800', silver: 'bg-gray-100 text-gray-800', bronze: 'bg-amber-100 text-amber-800' }[customerData.pricing_tier] || 'bg-blue-100 text-blue-800'
                }`}>
                  {customerData.pricing_tier?.toUpperCase()}
                </span>
              )}
            </div>
          </div>

          {/* Credit bar */}
          {profile.creditLimit > 0 && (
            <div className="w-full sm:w-64">
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>Credit Used: {fmt$(profile.balanceDue || 0)}</span>
                <span>Limit: {fmt$(profile.creditLimit)}</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className={`h-2 rounded-full ${
                    profile.creditUtilization > 80 ? 'bg-red-500' : profile.creditUtilization > 50 ? 'bg-yellow-500' : 'bg-green-500'
                  }`}
                  style={{ width: `${Math.min(profile.creditUtilization || 0, 100)}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-sm text-red-700">{error.response?.data?.detail || error.message}</p>
        </div>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <KPICard loading={isLoading} title="Sales YTD" value={fmt$(d.salesYTD || 0)} delta={d.salesDeltaPct} sub="vs prior year" />
        <KPICard loading={isLoading} title="Orders YTD" value={d.ordersYTD || 0} delta={d.ordersPY ? ((d.ordersYTD - d.ordersPY) / d.ordersPY * 100) : null} sub="vs prior year" />
        <KPICard loading={isLoading} title="Avg Order Value" value={fmt$(d.avgOrderValue || 0)} delta={d.avgOrderValuePY ? ((d.avgOrderValue - d.avgOrderValuePY) / d.avgOrderValuePY * 100) : null} sub="vs prior year" />
        <KPICard loading={isLoading} title="On-Time Delivery %" value={`${d.otdPct || 0}%`} sub="year to date" />
        <KPICard loading={isLoading} title="Open Orders" value={d.openOrders || 0} sub={d.openOrderValue ? fmt$(d.openOrderValue) : null} />
      </div>

      {/* Monthly sales chart */}
      <div className="bg-white shadow rounded-lg p-5">
        <h3 className="text-sm font-medium text-gray-700 mb-4">Monthly Sales YTD</h3>
        {isLoading ? (
          <div className="h-64 bg-gray-100 rounded animate-pulse" />
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={d.monthlySales || []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={{ fontSize: 12 }} />
              <YAxis tickFormatter={(v) => fmt$(v)} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v) => fmt$(v)} />
              <Bar dataKey="sales" name="Sales" fill="#4F46E5" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Recent shipments */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-sm font-medium text-gray-700">Recent Shipments</h3>
        </div>
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="p-4 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-8 bg-gray-100 rounded animate-pulse" />)}
            </div>
          ) : !d.recentShipments?.length ? (
            <div className="p-6 text-center text-sm text-gray-500">No recent shipments</div>
          ) : (
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Shipment #</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Order #</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Ship Date</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Requested Date</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {d.recentShipments.map((s, i) => {
                  const shipDate = s.postingDate
                  const promised = s.requestedDeliveryDate
                  const onTime = !promised || !shipDate || shipDate <= promised
                  return (
                    <tr key={i}>
                      <td className="px-6 py-3 text-sm font-mono text-gray-900">{s.number}</td>
                      <td className="px-6 py-3 text-sm text-gray-500">{s.orderNo || '—'}</td>
                      <td className="px-6 py-3 text-sm text-gray-500">{shipDate}</td>
                      <td className="px-6 py-3 text-sm text-gray-500">{promised || 'N/A'}</td>
                      <td className="px-6 py-3">
                        {!promised ? (
                          <span className="text-xs text-gray-400">N/A</span>
                        ) : (
                          <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${
                            onTime ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                          }`}>
                            {onTime ? 'ON TIME' : 'LATE'}
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

export default CustomerDetail
