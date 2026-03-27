import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { metricsApi } from '../api/client'
import { useAuth } from '../contexts/AuthContext'

const COLORS = ['#4F46E5', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16', '#F97316', '#6366F1']

function fmt$(val) {
  if (val >= 1_000_000) return `$${(val / 1_000_000).toFixed(1)}M`
  if (val >= 1_000) return `$${(val / 1_000).toFixed(1)}K`
  return `$${val.toFixed(0)}`
}

function DeltaBadge({ value, suffix = '%' }) {
  if (value == null || value === 0) return <span className="text-xs text-gray-400">—</span>
  const up = value > 0
  return (
    <span className={`text-xs font-medium ${up ? 'text-green-600' : 'text-red-600'}`}>
      {up ? '\u25B2' : '\u25BC'} {Math.abs(value).toFixed(1)}{suffix}
    </span>
  )
}

function KPICard({ title, value, delta, deltaLabel, sub, loading }) {
  if (loading) {
    return (
      <div className="bg-white shadow rounded-lg p-5 animate-pulse">
        <div className="h-3 bg-gray-200 rounded w-24 mb-3" />
        <div className="h-7 bg-gray-200 rounded w-32 mb-2" />
        <div className="h-3 bg-gray-200 rounded w-20" />
      </div>
    )
  }
  return (
    <div className="bg-white shadow rounded-lg p-5">
      <p className="text-sm text-gray-500 truncate">{title}</p>
      <p className="mt-1 text-2xl font-bold text-gray-900">{value}</p>
      <div className="mt-1 flex items-center gap-2">
        {delta != null && <DeltaBadge value={delta} />}
        {deltaLabel && <span className="text-xs text-gray-400">{deltaLabel}</span>}
        {sub && <span className="text-xs text-gray-500">{sub}</span>}
      </div>
    </div>
  )
}

// ============================================================================
// EXECUTIVE VIEW
// ============================================================================
function ExecutiveView() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['metrics', 'executive'],
    queryFn: async () => { const r = await metricsApi.getExecutive(); return r.data.data },
    staleTime: 300_000,
  })

  if (error) return <ErrorBanner message={error.response?.data?.detail || error.message} />

  const d = data || {}

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <KPICard loading={isLoading} title="Revenue YTD" value={fmt$(d.revenueYTD || 0)} delta={d.revenueDeltaPct} deltaLabel="vs prior year" />
        <KPICard loading={isLoading} title="Orders Shipped" value={d.ordersShipped?.toLocaleString() || '0'} />
        <KPICard loading={isLoading} title="Avg Order Value" value={fmt$(d.avgOrderValue || 0)} delta={d.avgOrderValuePY ? ((d.avgOrderValue - d.avgOrderValuePY) / d.avgOrderValuePY * 100) : null} deltaLabel="vs prior year" />
        <KPICard loading={isLoading} title="Active Customers" value={d.activeCustomers || 0} sub={d.newCustomers ? `${d.newCustomers} new this year` : null} />
        <KPICard loading={isLoading} title="On-Time Delivery %" value={`${d.otdPct || 0}%`} sub={d.otdTotal ? `${d.otdOnTime}/${d.otdTotal} shipments (30d)` : null} />
        <KPICard loading={isLoading} title="Accounts Receivable" value={fmt$(d.arTotal || 0)} sub={d.arCount ? `${d.arCount} accounts` : null} />
        <KPICard loading={isLoading} title="Accounts Payable" value={fmt$(d.apTotal || 0)} sub={d.apCount ? `${d.apCount} vendors` : null} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Revenue chart */}
        <div className="bg-white shadow rounded-lg p-5">
          <h3 className="text-sm font-medium text-gray-700 mb-4">Monthly Revenue vs Prior Year</h3>
          {isLoading ? <ChartSkeleton /> : (
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={d.monthlyRevenue || []}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={(v) => fmt$(v)} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v) => fmt$(v)} />
                <Legend />
                <Area type="monotone" dataKey="current" name="This Year" stroke="#4F46E5" fill="#4F46E5" fillOpacity={0.15} />
                <Area type="monotone" dataKey="prior" name="Prior Year" stroke="#9CA3AF" fill="#9CA3AF" fillOpacity={0.08} strokeDasharray="4 4" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Product mix */}
        <div className="bg-white shadow rounded-lg p-5">
          <h3 className="text-sm font-medium text-gray-700 mb-4">Product Mix by Revenue</h3>
          {isLoading ? <ChartSkeleton /> : (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie data={d.productMix || []} cx="50%" cy="50%" outerRadius={100} dataKey="value" nameKey="name" label={({ name, percent }) => `${name.substring(0, 15)} ${(percent * 100).toFixed(0)}%`} labelLine={false}>
                  {(d.productMix || []).map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v) => fmt$(v)} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Top accounts */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-sm font-medium text-gray-700">Top 10 Accounts</h3>
        </div>
        <div className="overflow-x-auto">
          {isLoading ? <TableSkeleton rows={5} /> : (
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Customer</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">YTD Revenue</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Orders</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {(d.topAccounts || []).map((a, i) => (
                  <tr key={i}>
                    <td className="px-6 py-3 text-sm text-gray-900">{a.name}</td>
                    <td className="px-6 py-3 text-sm text-right text-gray-900 font-medium">{fmt$(a.revenue)}</td>
                    <td className="px-6 py-3 text-sm text-right text-gray-500">{a.orders}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// OPERATIONS VIEW
// ============================================================================
function OperationsView() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['metrics', 'operations'],
    queryFn: async () => { const r = await metricsApi.getOperations(); return r.data.data },
    staleTime: 120_000,
  })

  if (error) return <ErrorBanner message={error.response?.data?.detail || error.message} />

  const d = data || {}

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <KPICard loading={isLoading} title="Open Orders" value={d.openOrders || 0} sub={d.overdueOrders ? `${d.overdueOrders} overdue` : null} />
        <KPICard loading={isLoading} title="Orders This Week" value={d.ordersThisWeek || 0} />
        <KPICard loading={isLoading} title="Shipments Today" value={d.shipmentsToday || 0} />
        <KPICard loading={isLoading} title="Commit Date Met %" value={`${d.commitDateMetPct || 0}%`} sub="rolling 30 days" />
      </div>

      {/* Daily shipments chart */}
      <div className="bg-white shadow rounded-lg p-5">
        <h3 className="text-sm font-medium text-gray-700 mb-4">Daily Shipments This Week</h3>
        {isLoading ? <ChartSkeleton /> : (
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={d.dailyShipments || []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="day" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="onTime" name="On Time" fill="#10B981" stackId="a" />
              <Bar dataKey="late" name="Late" fill="#EF4444" stackId="a" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Monthly shipments by week */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white shadow rounded-lg p-5">
          <h3 className="text-sm font-medium text-gray-700 mb-4">Shipments This Month (by week)</h3>
          {isLoading ? <ChartSkeleton /> : (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={d.weeklyShipments || []}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="week" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="shipments" name="Shipments" fill="#4F46E5" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="bg-white shadow rounded-lg p-5">
          <h3 className="text-sm font-medium text-gray-700 mb-4">Shipment Value This Month (by week)</h3>
          {isLoading ? <ChartSkeleton /> : (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={d.weeklyShipments || []}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="week" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={(v) => fmt$(v)} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v) => fmt$(v)} />
                <Bar dataKey="value" name="Value" fill="#10B981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Overdue orders */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-sm font-medium text-gray-700">Overdue Orders</h3>
        </div>
        <div className="overflow-x-auto">
          {isLoading ? <TableSkeleton rows={5} /> : (
            !d.overdueDetail?.length ? (
              <div className="p-6 text-center text-sm text-gray-500">No overdue orders</div>
            ) : (
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Order #</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Customer</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Days Late</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Value</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Requested Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {d.overdueDetail.map((o, i) => (
                    <tr key={i} className="bg-red-50">
                      <td className="px-6 py-3 text-sm font-mono text-gray-900">{o.orderNo}</td>
                      <td className="px-6 py-3 text-sm text-gray-900">{o.customer}</td>
                      <td className="px-6 py-3 text-sm text-right text-red-600 font-medium">{o.daysLate}d</td>
                      <td className="px-6 py-3 text-sm text-right text-gray-900">{fmt$(o.value || 0)}</td>
                      <td className="px-6 py-3 text-sm text-gray-500">{o.requestedDate}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          )}
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// SHIPPING VIEW
// ============================================================================
function ShippingView() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['metrics', 'shipping'],
    queryFn: async () => { const r = await metricsApi.getShipping(); return r.data.data },
    staleTime: 120_000,
  })

  if (error) return <ErrorBanner message={error.response?.data?.detail || error.message} />

  const d = data || {}

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard loading={isLoading} title="Due Today" value={d.shipmentsDueToday || 0} />
        <KPICard loading={isLoading} title="Overdue Shipments" value={d.overdueShipments || 0} />
        <KPICard loading={isLoading} title="Avg Days to Ship" value={`${d.avgDaysToShip || 0}d`} sub="rolling 30 days" />
        <KPICard loading={isLoading} title="Total Open Orders" value={d.totalOpenOrders || 0} />
      </div>

      {/* Ship queue */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-sm font-medium text-gray-700">Today's Ship Queue</h3>
        </div>
        <div className="overflow-x-auto">
          {isLoading ? <TableSkeleton rows={8} /> : (
            !d.shipQueue?.length ? (
              <div className="p-6 text-center text-sm text-gray-500">No shipments due today</div>
            ) : (
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Order #</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Customer</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Requested Date</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Value</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {d.shipQueue.map((s, i) => (
                    <tr key={i} className={s.status === 'overdue' ? 'bg-red-50' : ''}>
                      <td className="px-6 py-3 text-sm font-mono text-gray-900">{s.orderNo}</td>
                      <td className="px-6 py-3 text-sm text-gray-900">{s.customer}</td>
                      <td className="px-6 py-3 text-sm text-gray-500">{s.requestedDate}</td>
                      <td className="px-6 py-3 text-sm text-right text-gray-900">{fmt$(s.value || 0)}</td>
                      <td className="px-6 py-3">
                        <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${
                          s.status === 'overdue' ? 'bg-red-100 text-red-800' : 'bg-yellow-100 text-yellow-800'
                        }`}>
                          {s.status === 'overdue' ? 'OVERDUE' : 'DUE TODAY'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          )}
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// SHARED COMPONENTS
// ============================================================================
function ChartSkeleton() {
  return <div className="h-64 bg-gray-100 rounded animate-pulse" />
}

function TableSkeleton({ rows = 5 }) {
  return (
    <div className="p-4 space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 bg-gray-100 rounded animate-pulse" />
      ))}
    </div>
  )
}

function ErrorBanner({ message }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-4">
      <p className="text-sm text-red-700">{message}</p>
    </div>
  )
}

// ============================================================================
// MAIN DASHBOARD
// ============================================================================
function BusinessDashboard() {
  const { user } = useAuth()
  const role = user?.role || 'viewer'

  // Determine available tabs based on role
  const tabs = []
  if (role === 'admin') tabs.push({ id: 'executive', label: 'Executive' })
  if (role === 'admin' || role === 'reviewer') tabs.push({ id: 'operations', label: 'Operations' })
  tabs.push({ id: 'shipping', label: 'Shipping' })

  const [activeTab, setActiveTab] = useState(tabs[0]?.id || 'shipping')

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Business Dashboard</h1>
          <p className="mt-1 text-sm text-gray-500">Live metrics from Business Central</p>
        </div>
      </div>

      {/* Tab switcher */}
      {tabs.length > 1 && (
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-8">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium ${
                  activeTab === tab.id
                    ? 'border-odc-600 text-odc-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      )}

      {/* View content */}
      {activeTab === 'executive' && <ExecutiveView />}
      {activeTab === 'operations' && <OperationsView />}
      {activeTab === 'shipping' && <ShippingView />}
    </div>
  )
}

export default BusinessDashboard
