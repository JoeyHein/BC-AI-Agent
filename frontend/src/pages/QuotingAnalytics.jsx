import { useState, useEffect } from 'react'
import { metricsApi } from '../api/client'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie, Legend,
} from 'recharts'

const COLORS = ['#4F46E5', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16', '#F97316', '#6366F1']
const BLUE_RAMP = ['#1e3a5f', '#1e40af', '#2563eb', '#3b82f6', '#60a5fa', '#93bbfd', '#a5c4fd', '#bfdbfe', '#dbeafe', '#eff6ff']

const fmt = (v) => {
  if (v == null) return '--'
  return '$' + Number(v).toLocaleString('en-CA', { maximumFractionDigits: 0 })
}

const Badge = ({ rate }) => {
  const color = rate >= 50 ? 'green' : rate >= 25 ? 'yellow' : 'red'
  return (
    <span className={`px-2 py-0.5 text-xs font-semibold rounded-full bg-${color}-100 text-${color}-800`}>
      {rate}%
    </span>
  )
}

const StatusBadge = ({ status, label }) => {
  const map = { green: 'bg-green-100 text-green-800', amber: 'bg-yellow-100 text-yellow-800', red: 'bg-red-100 text-red-800' }
  return <span className={`px-2 py-0.5 text-xs font-semibold rounded-full ${map[status] || map.green}`}>{label}</span>
}

const Skeleton = ({ className = '' }) => (
  <div className={`animate-pulse bg-gray-200 rounded ${className}`} />
)

export default function QuotingAnalytics() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [days, setDays] = useState(30)

  const fetchData = async (d) => {
    setLoading(true)
    setError(null)
    try {
      const res = await metricsApi.getQuoting(d)
      setData(res.data.data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load analytics')
    }
    setLoading(false)
  }

  useEffect(() => { fetchData(days) }, [days])

  const periods = [
    { label: '7d', value: 7 },
    { label: '30d', value: 30 },
    { label: '90d', value: 90 },
    { label: '12m', value: 365 },
  ]

  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <p className="text-red-800 font-medium mb-3">Failed to load quoting analytics</p>
          <p className="text-red-600 text-sm mb-4">{error}</p>
          <button onClick={() => fetchData(days)} className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm">
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Quoting Analytics</h1>
          <p className="text-sm text-gray-500 mt-1">Pipeline, conversion, and quote performance</p>
        </div>
        <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
          {periods.map(p => (
            <button
              key={p.value}
              onClick={() => setDays(p.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                days === p.value ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* 1. Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        {loading ? (
          Array(4).fill(0).map((_, i) => (
            <div key={i} className="bg-white rounded-lg shadow p-5">
              <Skeleton className="h-4 w-24 mb-3" />
              <Skeleton className="h-8 w-20" />
            </div>
          ))
        ) : (
          <>
            <div className="bg-white rounded-lg shadow p-5">
              <p className="text-sm font-medium text-gray-500">Open Quote Value</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{fmt(data?.summary?.total_open_value)}</p>
            </div>
            <div className="bg-white rounded-lg shadow p-5">
              <p className="text-sm font-medium text-gray-500">Conversion Rate</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{data?.summary?.conversion_rate ?? '--'}%</p>
              <p className="text-xs text-gray-400 mt-1">{data?.summary?.total_orders_in_period} orders / {data?.summary?.total_quotes_in_period} quotes</p>
            </div>
            <div className="bg-white rounded-lg shadow p-5">
              <p className="text-sm font-medium text-gray-500">Expiring in 7 Days</p>
              <p className={`text-2xl font-bold mt-1 ${(data?.summary?.expiring_soon || 0) > 0 ? 'text-red-600' : 'text-gray-900'}`}>
                {data?.summary?.expiring_soon ?? 0}
              </p>
            </div>
            <div className="bg-white rounded-lg shadow p-5">
              <p className="text-sm font-medium text-gray-500">Avg Quote Age</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{data?.summary?.avg_age_days ?? '--'} days</p>
            </div>
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* 2. Quote frequency by customer */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Quotes by Customer (Top 10)</h3>
          {loading ? <Skeleton className="h-64 w-full" /> : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={data?.quote_by_customer || []} layout="vertical" margin={{ left: 100 }}>
                <XAxis type="number" />
                <YAxis type="category" dataKey="customer" width={100} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" name="Quotes" radius={[0, 4, 4, 0]}>
                  {(data?.quote_by_customer || []).map((_, i) => (
                    <Cell key={i} fill={BLUE_RAMP[Math.min(i, BLUE_RAMP.length - 1)]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* 6. Pipeline by account type (donut) */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Open Pipeline by Account Type</h3>
          {loading ? <Skeleton className="h-64 w-full" /> : (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={(data?.pipeline_by_type || []).filter(d => d.value > 0)}
                  cx="50%" cy="50%"
                  innerRadius={60} outerRadius={100}
                  paddingAngle={3}
                  dataKey="value"
                  nameKey="type"
                  label={({ type, value }) => `${type}: ${fmt(value)}`}
                >
                  {(data?.pipeline_by_type || []).filter(d => d.value > 0).map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => fmt(v)} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* 5. Quote aging */}
      <div className="bg-white rounded-lg shadow p-6 mb-8">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Open Quote Aging</h3>
        {loading ? <Skeleton className="h-20 w-full" /> : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {(data?.aging || []).map(bucket => (
              <div key={bucket.bucket} className="border rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-700">{bucket.bucket}</span>
                  <StatusBadge status={bucket.status} label={bucket.label} />
                </div>
                <p className="text-2xl font-bold text-gray-900">{bucket.count}</p>
                <p className="text-xs text-gray-500">{fmt(bucket.value)}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 7. Quote volume over time */}
      <div className="bg-white rounded-lg shadow p-6 mb-8">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Quote Volume (12 Months)</h3>
        {loading ? <Skeleton className="h-64 w-full" /> : (
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={data?.volume_over_time || []}>
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" name="Quotes" fill="#4F46E5" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* 3. Conversion by customer (table) */}
      <div className="bg-white rounded-lg shadow p-6 mb-8">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Quote-to-Order Conversion by Customer</h3>
        {loading ? <Skeleton className="h-48 w-full" /> : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Customer</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase"># Quotes</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase"># Orders</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Conversion</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(data?.conversion_by_customer || []).slice(0, 15).map((row, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-sm text-gray-900">{row.customer}</td>
                    <td className="px-4 py-2 text-sm text-gray-600 text-right">{row.quotes}</td>
                    <td className="px-4 py-2 text-sm text-gray-600 text-right">{row.orders}</td>
                    <td className="px-4 py-2 text-right"><Badge rate={row.rate} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(!data?.conversion_by_customer?.length) && (
              <p className="text-center text-gray-400 py-4 text-sm">No data for this period</p>
            )}
          </div>
        )}
      </div>

      {/* 4. Most-quoted items not converting */}
      {data?.items_not_converting?.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6 mb-8">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Most-Quoted Items Not Converting</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Item</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Times Quoted</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Times Ordered</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Conversion</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.items_not_converting.map((row, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-sm text-gray-900">{row.item}</td>
                    <td className="px-4 py-2 text-sm text-gray-600 text-right">{row.times_quoted}</td>
                    <td className="px-4 py-2 text-sm text-gray-600 text-right">{row.times_ordered}</td>
                    <td className="px-4 py-2 text-right"><Badge rate={row.rate} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 8. Quote revision frequency */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Quote Complexity</h3>
        {loading ? <Skeleton className="h-20 w-full" /> : (
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: 'Simple (1-3 items)', count: data?.revision_frequency?.simple || 0, color: 'green' },
              { label: 'Moderate (4-10 items)', count: data?.revision_frequency?.moderate || 0, color: 'yellow' },
              { label: 'Complex (10+ items)', count: data?.revision_frequency?.complex || 0, color: 'red' },
            ].map(r => {
              const total = (data?.revision_frequency?.simple || 0) + (data?.revision_frequency?.moderate || 0) + (data?.revision_frequency?.complex || 0)
              const pct = total > 0 ? Math.round(r.count / total * 100) : 0
              return (
                <div key={r.label} className="text-center">
                  <p className="text-2xl font-bold text-gray-900">{r.count}</p>
                  <p className="text-xs text-gray-500 mb-2">{r.label}</p>
                  <div className="w-full bg-gray-100 rounded-full h-1.5">
                    <div className={`h-1.5 rounded-full bg-${r.color}-500`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
