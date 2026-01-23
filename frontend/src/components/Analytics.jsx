import { useState, useEffect } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend
} from 'recharts'
import { analyticsApi } from '../api/client'

// Color palette for charts
const COLORS = ['#4F46E5', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16']

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center p-8">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
    </div>
  )
}

function ErrorMessage({ message }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-4">
      <p className="text-red-800">{message}</p>
    </div>
  )
}

function StatCard({ title, value, subtitle, icon }) {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center">
        <div className="flex-shrink-0">
          <div className="w-12 h-12 bg-indigo-100 rounded-lg flex items-center justify-center text-indigo-600">
            {icon}
          </div>
        </div>
        <div className="ml-4">
          <p className="text-sm font-medium text-gray-500">{title}</p>
          <p className="text-2xl font-semibold text-gray-900">{value}</p>
          {subtitle && <p className="text-sm text-gray-500">{subtitle}</p>}
        </div>
      </div>
    </div>
  )
}

function TopItemsChart({ data }) {
  if (!data || data.length === 0) {
    return <p className="text-gray-500 text-center py-8">No item data available</p>
  }

  const chartData = data.slice(0, 10).map(item => ({
    name: item.item_number.length > 15 ? item.item_number.substring(0, 15) + '...' : item.item_number,
    fullName: item.item_number,
    quotes: item.quote_count,
    revenue: Math.round(item.total_revenue)
  }))

  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 20 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" />
          <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 12 }} />
          <Tooltip
            formatter={(value, name) => [
              name === 'quotes' ? `${value} quotes` : `$${value.toLocaleString()}`,
              name === 'quotes' ? 'Quote Count' : 'Revenue'
            ]}
            labelFormatter={(label, payload) => payload[0]?.payload?.fullName || label}
          />
          <Bar dataKey="quotes" fill="#4F46E5" name="quotes" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function TopCustomersTable({ data }) {
  if (!data || data.length === 0) {
    return <p className="text-gray-500 text-center py-8">No customer data available</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Customer</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Quotes</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Total Value</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Avg Value</th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {data.slice(0, 10).map((customer, idx) => (
            <tr key={customer.customer_number} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              <td className="px-6 py-4 whitespace-nowrap">
                <div className="text-sm font-medium text-gray-900">{customer.customer_name}</div>
                <div className="text-sm text-gray-500">{customer.customer_number}</div>
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{customer.quote_count}</td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                ${customer.total_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                ${customer.avg_quote_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ItemAffinityTable({ data }) {
  if (!data || data.length === 0) {
    return <p className="text-gray-500 text-center py-8">No affinity data available</p>
  }

  const getStrengthBadge = (lift) => {
    if (lift > 3) return <span className="px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800">Very Strong</span>
    if (lift > 2) return <span className="px-2 py-1 text-xs font-semibold rounded-full bg-blue-100 text-blue-800">Strong</span>
    if (lift > 1.5) return <span className="px-2 py-1 text-xs font-semibold rounded-full bg-yellow-100 text-yellow-800">Moderate</span>
    return <span className="px-2 py-1 text-xs font-semibold rounded-full bg-gray-100 text-gray-800">Weak</span>
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Item A</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Item B</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Together</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Lift</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Strength</th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {data.slice(0, 15).map((assoc, idx) => (
            <tr key={`${assoc.item_a}-${assoc.item_b}`} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{assoc.item_a}</td>
              <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{assoc.item_b}</td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{assoc.pair_count} quotes</td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{assoc.lift.toFixed(2)}x</td>
              <td className="px-6 py-4 whitespace-nowrap">{getStrengthBadge(assoc.lift)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RevenueByItemChart({ data }) {
  if (!data || data.length === 0) {
    return <p className="text-gray-500 text-center py-8">No revenue data available</p>
  }

  const chartData = data
    .filter(item => item.total_revenue > 1000)
    .slice(0, 8)
    .map(item => ({
      name: item.item_number.length > 12 ? item.item_number.substring(0, 12) + '...' : item.item_number,
      value: Math.round(item.total_revenue)
    }))

  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            labelLine={false}
            label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
            outerRadius={100}
            fill="#8884d8"
            dataKey="value"
          >
            {chartData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(value) => `$${value.toLocaleString()}`} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

function CustomerRecommendations({ customerNumber, customerName }) {
  const [recommendations, setRecommendations] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!customerNumber) return

    const fetchRecommendations = async () => {
      try {
        setLoading(true)
        const response = await analyticsApi.getCustomerRecommendations(customerNumber)
        setRecommendations(response.data.data)
      } catch (err) {
        setError('Failed to load recommendations')
      } finally {
        setLoading(false)
      }
    }

    fetchRecommendations()
  }, [customerNumber])

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorMessage message={error} />
  if (!recommendations?.recommendations?.length) {
    return <p className="text-gray-500 text-center py-4">No recommendations available for this customer</p>
  }

  return (
    <div className="bg-gray-50 rounded-lg p-4">
      <h4 className="font-medium text-gray-900 mb-3">Recommended Items for {customerName}</h4>
      <ul className="space-y-2">
        {recommendations.recommendations.slice(0, 5).map((rec, idx) => (
          <li key={idx} className="flex justify-between items-center text-sm">
            <span className="font-medium text-gray-900">{rec.item}</span>
            <span className="text-gray-500">{rec.reason}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Analytics() {
  const [activeTab, setActiveTab] = useState('overview')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [dashboardData, setDashboardData] = useState(null)
  const [itemFrequency, setItemFrequency] = useState(null)
  const [customerPreferences, setCustomerPreferences] = useState(null)
  const [itemAffinity, setItemAffinity] = useState(null)
  const [selectedCustomer, setSelectedCustomer] = useState(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)
        setError(null)

        // Fetch dashboard summary first
        const summaryResponse = await analyticsApi.getDashboardSummary()
        setDashboardData(summaryResponse.data.data)

        // Fetch detailed data based on tab
        const [freqResponse, custResponse, affinityResponse] = await Promise.all([
          analyticsApi.getItemFrequency(),
          analyticsApi.getCustomerPreferences(),
          analyticsApi.getItemAffinity()
        ])

        setItemFrequency(freqResponse.data.data)
        setCustomerPreferences(custResponse.data.data)
        setItemAffinity(affinityResponse.data.data)

      } catch (err) {
        console.error('Analytics fetch error:', err)
        setError('Failed to load analytics data. Please ensure the backend is running.')
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [])

  const tabs = [
    { id: 'overview', name: 'Overview' },
    { id: 'items', name: 'Top Items' },
    { id: 'customers', name: 'Customers' },
    { id: 'affinity', name: 'Item Affinity' },
  ]

  if (loading) {
    return (
      <div className="bg-white shadow rounded-lg p-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-4">Quote Analytics</h1>
        <LoadingSpinner />
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white shadow rounded-lg p-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-4">Quote Analytics</h1>
        <ErrorMessage message={error} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Quote Analytics</h1>
            <p className="text-gray-500 mt-1">AI-powered insights from your quote history</p>
          </div>
          <div className="text-sm text-gray-500">
            Last updated: {dashboardData?.analysis_date ? new Date(dashboardData.analysis_date).toLocaleString() : 'N/A'}
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Quotes Analyzed"
          value={dashboardData?.quotes_analyzed || 0}
          icon={<svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>}
        />
        <StatCard
          title="Unique Items"
          value={dashboardData?.unique_items || 0}
          icon={<svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" /></svg>}
        />
        <StatCard
          title="Customers"
          value={dashboardData?.unique_customers || 0}
          icon={<svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" /></svg>}
        />
        <StatCard
          title="Avg Quote Value"
          value={`$${(dashboardData?.avg_quote_value || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          subtitle={`Median: $${(dashboardData?.median_quote_value || 0).toLocaleString()}`}
          icon={<svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
        />
      </div>

      {/* Tabs */}
      <div className="bg-white shadow rounded-lg">
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-8 px-6" aria-label="Tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-4 px-1 border-b-2 font-medium text-sm ${
                  activeTab === tab.id
                    ? 'border-indigo-500 text-indigo-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {tab.name}
              </button>
            ))}
          </nav>
        </div>

        <div className="p-6">
          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-4">Top Items by Quote Frequency</h3>
                <TopItemsChart data={itemFrequency?.top_items} />
              </div>
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-4">Revenue Distribution</h3>
                <RevenueByItemChart data={itemFrequency?.top_items} />
              </div>
            </div>
          )}

          {/* Items Tab */}
          {activeTab === 'items' && (
            <div>
              <h3 className="text-lg font-medium text-gray-900 mb-4">All Items Ranked by Frequency</h3>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Rank</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Item</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Description</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Quotes</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Total Qty</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Revenue</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {itemFrequency?.full_ranking?.slice(0, 30).map((item, idx) => (
                      <tr key={item.item_number} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{idx + 1}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{item.item_number}</td>
                        <td className="px-6 py-4 text-sm text-gray-500 max-w-xs truncate">{item.description}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{item.quote_count}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{item.total_quantity}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          ${item.total_revenue?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Customers Tab */}
          {activeTab === 'customers' && (
            <div className="space-y-6">
              <div>
                <h3 className="text-lg font-medium text-gray-900 mb-4">Top Customers by Value</h3>
                <TopCustomersTable data={customerPreferences?.all_customers} />
              </div>

              {selectedCustomer && (
                <CustomerRecommendations
                  customerNumber={selectedCustomer.customer_number}
                  customerName={selectedCustomer.customer_name}
                />
              )}

              <div className="mt-4">
                <h4 className="text-sm font-medium text-gray-700 mb-2">Select a customer for recommendations:</h4>
                <select
                  className="block w-full max-w-md rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                  onChange={(e) => {
                    const cust = customerPreferences?.all_customers?.find(c => c.customer_number === e.target.value)
                    setSelectedCustomer(cust)
                  }}
                  value={selectedCustomer?.customer_number || ''}
                >
                  <option value="">Select customer...</option>
                  {customerPreferences?.all_customers?.map(c => (
                    <option key={c.customer_number} value={c.customer_number}>
                      {c.customer_name} ({c.customer_number})
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* Affinity Tab */}
          {activeTab === 'affinity' && (
            <div>
              <div className="mb-4">
                <h3 className="text-lg font-medium text-gray-900">Items Frequently Quoted Together</h3>
                <p className="text-sm text-gray-500 mt-1">
                  These items have a strong association - when one is quoted, the other often appears too.
                  Use this for cross-selling and bundle recommendations.
                </p>
              </div>
              <ItemAffinityTable data={itemAffinity?.strong_associations || itemAffinity?.all_associations} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Analytics
