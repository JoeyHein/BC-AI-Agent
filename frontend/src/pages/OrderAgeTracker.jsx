import { useEffect, useState } from 'react'
import { metricsApi } from '../api/client'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { formatDate, formatDateTime } from '../utils/datetime'

// Bucket colors — match the row coloring legend.
const OPEN_BUCKET_COLORS = {
  green: '#10B981',
  yellow: '#F59E0B',
  red: '#EF4444',
}

const SUCCESS_BUCKET_COLORS = {
  under_4w: '#10B981',
  under_6w: '#F59E0B',
  under_8w: '#F97316',
  over_8w: '#EF4444',
}

const STATUS_LABELS = {
  pending: 'Pending',
  confirmed: 'Confirmed',
  in_production: 'In Production',
  ready_to_ship: 'Ready to Ship',
}

function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return formatDate(iso, 'en-CA', { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

function fmtMoney(v) {
  if (v == null) return '—'
  return '$' + Number(v).toLocaleString('en-CA', { maximumFractionDigits: 0 })
}

function rowClass(bucket) {
  switch (bucket) {
    case 'green':  return 'bg-green-50 hover:bg-green-100'
    case 'yellow': return 'bg-yellow-50 hover:bg-yellow-100'
    case 'red':    return 'bg-red-50 hover:bg-red-100'
    default:       return 'hover:bg-gray-50'
  }
}

function ageDot(bucket) {
  const cls = {
    green: 'bg-green-500',
    yellow: 'bg-yellow-500',
    red: 'bg-red-500',
  }[bucket] || 'bg-gray-300'
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${cls} mr-2 align-middle`} />
}

function KpiTile({ label, value, suffix = '%', count, color, bgClass }) {
  return (
    <div className={`rounded-lg p-5 border ${bgClass}`}>
      <p className="text-xs uppercase tracking-wider text-gray-600 font-medium">{label}</p>
      <p className="mt-2 text-3xl font-bold" style={{ color }}>
        {value}<span className="text-xl ml-1">{suffix}</span>
      </p>
      <p className="mt-1 text-xs text-gray-500">{count} orders</p>
    </div>
  )
}

function Skeleton({ h = 'h-4', w = 'w-full' }) {
  return <div className={`animate-pulse bg-gray-200 rounded ${h} ${w}`} />
}

export default function OrderAgeTracker() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lookback, setLookback] = useState(90)

  const fetchData = async (lb) => {
    setLoading(true); setError(null)
    try {
      const res = await metricsApi.getOrderAge(lb)
      setData(res.data.data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load order age')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData(lookback) }, [lookback])

  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <p className="text-red-800 font-medium mb-3">Failed to load Order Age Tracker</p>
          <p className="text-red-600 text-sm mb-4">{error}</p>
          <button onClick={() => fetchData(lookback)} className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm">
            Retry
          </button>
        </div>
      </div>
    )
  }

  const sr = data?.success_rate
  const openRows = data?.open_orders || []
  const openSummary = data?.open_summary || { total: 0, green: 0, yellow: 0, red: 0 }

  // Chart data for open-order distribution
  const openChart = [
    { label: 'Under 4 wks', count: openSummary.green, color: OPEN_BUCKET_COLORS.green },
    { label: '4 – 6 wks',   count: openSummary.yellow, color: OPEN_BUCKET_COLORS.yellow },
    { label: 'Over 6 wks',  count: openSummary.red,    color: OPEN_BUCKET_COLORS.red },
  ]

  const periods = [
    { label: '30d', value: 30 },
    { label: '90d', value: 90 },
    { label: '12m', value: 365 },
  ]

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Order Age Tracker</h1>
          <p className="text-sm text-gray-500 mt-1">
            Open-order aging and team delivery performance
          </p>
        </div>
        <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
          {periods.map(p => (
            <button
              key={p.value}
              onClick={() => setLookback(p.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                lookback === p.value ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Success rate KPI tiles */}
      <section className="mb-8">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
            Delivery Success Rate
          </h2>
          {sr && (
            <p className="text-xs text-gray-500">
              {sr.shipped_count} shipped in last {sr.lookback_days} days
              {sr.avg_days_to_ship != null && ` · avg ${sr.avg_days_to_ship}d to ship`}
            </p>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {loading || !sr ? (
            Array(4).fill(0).map((_, i) => <Skeleton key={i} h="h-28" />)
          ) : (
            <>
              <KpiTile
                label="Shipped ≤ 4 weeks"
                value={sr.under_4w}
                count={sr.buckets.under_4w}
                color={SUCCESS_BUCKET_COLORS.under_4w}
                bgClass="bg-green-50 border-green-200"
              />
              <KpiTile
                label="Shipped ≤ 6 weeks"
                value={sr.under_6w}
                count={sr.buckets.under_6w}
                color={SUCCESS_BUCKET_COLORS.under_6w}
                bgClass="bg-yellow-50 border-yellow-200"
              />
              <KpiTile
                label="Shipped ≤ 8 weeks"
                value={sr.under_8w}
                count={sr.buckets.under_8w}
                color={SUCCESS_BUCKET_COLORS.under_8w}
                bgClass="bg-orange-50 border-orange-200"
              />
              <KpiTile
                label="Over 8 weeks"
                value={sr.over_8w}
                count={sr.buckets.over_8w}
                color={SUCCESS_BUCKET_COLORS.over_8w}
                bgClass="bg-red-50 border-red-200"
              />
            </>
          )}
        </div>
      </section>

      {/* Open orders distribution + summary */}
      <section className="mb-8 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-4">
            Open Orders by Age
          </h2>
          {loading ? (
            <Skeleton h="h-64" />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={openChart} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
                <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {openChart.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-4">
            Currently Open
          </h2>
          {loading ? (
            <div className="space-y-3"><Skeleton /><Skeleton /><Skeleton /><Skeleton /></div>
          ) : (
            <ul className="space-y-3">
              <li className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Total open</span>
                <span className="text-2xl font-semibold text-gray-900">{openSummary.total}</span>
              </li>
              <li className="flex items-center justify-between">
                <span className="text-sm text-gray-600 flex items-center">{ageDot('green')}Under 4 weeks</span>
                <span className="text-lg font-medium text-green-700">{openSummary.green}</span>
              </li>
              <li className="flex items-center justify-between">
                <span className="text-sm text-gray-600 flex items-center">{ageDot('yellow')}4 – 6 weeks</span>
                <span className="text-lg font-medium text-yellow-700">{openSummary.yellow}</span>
              </li>
              <li className="flex items-center justify-between">
                <span className="text-sm text-gray-600 flex items-center">{ageDot('red')}Over 6 weeks</span>
                <span className="text-lg font-medium text-red-700">{openSummary.red}</span>
              </li>
            </ul>
          )}
        </div>
      </section>

      {/* Order list */}
      <section className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
            All Open Orders <span className="text-gray-400 font-normal normal-case">(oldest first)</span>
          </h2>
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <span className="flex items-center">{ageDot('green')}&lt; 4 wks</span>
            <span className="flex items-center">{ageDot('yellow')}4–6 wks</span>
            <span className="flex items-center">{ageDot('red')}&gt; 6 wks</span>
          </div>
        </div>
        <div className="overflow-x-auto">
          {loading ? (
            <div className="p-5 space-y-3">
              {Array(6).fill(0).map((_, i) => <Skeleton key={i} h="h-8" />)}
            </div>
          ) : openRows.length === 0 ? (
            <div className="p-12 text-center text-gray-500 text-sm">No open orders.</div>
          ) : (
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Order #</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Customer</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">PO</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Order Date</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Expected By</th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Age</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Status</th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {openRows.map(o => (
                  <tr key={o.id} className={rowClass(o.bucket)}>
                    <td className="px-4 py-2 text-sm font-medium text-gray-900 whitespace-nowrap">
                      {ageDot(o.bucket)}{o.bc_order_number || `#${o.id}`}
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-700 whitespace-nowrap">
                      {o.customer_name || o.customer_number || '—'}
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-600 whitespace-nowrap">{o.po_number || '—'}</td>
                    <td className="px-4 py-2 text-sm text-gray-600 whitespace-nowrap">{fmtDate(o.order_date)}</td>
                    <td className="px-4 py-2 text-sm whitespace-nowrap">
                      {o.requested_delivery_date ? (
                        <>
                          <span className="text-gray-700">{fmtDate(o.requested_delivery_date)}</span>
                          {o.days_until_due != null && (
                            <span className={
                              "ml-1 text-xs " +
                              (o.days_until_due < 0
                                ? "text-red-600 font-medium"
                                : o.days_until_due <= 7
                                  ? "text-yellow-700"
                                  : "text-gray-400")
                            }>
                              ({o.days_until_due < 0
                                ? `${Math.abs(o.days_until_due)}d overdue`
                                : `in ${o.days_until_due}d`})
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-sm text-right whitespace-nowrap font-medium">
                      <span className={
                        o.bucket === 'red' ? 'text-red-700'
                        : o.bucket === 'yellow' ? 'text-yellow-700'
                        : 'text-green-700'
                      }>
                        {o.age_weeks} wks
                      </span>
                      <span className="text-gray-400 ml-1">({o.age_days}d)</span>
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-600 whitespace-nowrap">
                      {STATUS_LABELS[o.status] || o.status || '—'}
                    </td>
                    <td className="px-4 py-2 text-sm text-right text-gray-700 whitespace-nowrap">{fmtMoney(o.total_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {data?.generated_at && (
        <p className="mt-4 text-xs text-gray-400 text-right">
          Updated {formatDateTime(data.generated_at, 'en-CA')}
        </p>
      )}
    </div>
  )
}
