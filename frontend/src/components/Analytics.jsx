import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ComposedChart, Line, ReferenceLine,
} from 'recharts'
import { formatDate } from '../utils/datetime'
import { metricsApi } from '../api/client'

const PERIODS = [
  { value: 'this_month',   label: 'This Month' },
  { value: 'last_month',   label: 'Last Month' },
  { value: 'this_quarter', label: 'This Quarter' },
  { value: 'last_quarter', label: 'Last Quarter' },
  { value: 'ytd',          label: 'YTD' },
  { value: '12m',          label: 'Last 12 Months' },
  { value: '24m',          label: 'Last 24 Months' },
]

function fmtMoney(v, opts = {}) {
  if (v == null) return '—'
  const { compact = false } = opts
  if (compact && Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (compact && Math.abs(v) >= 1_000)     return `$${(v / 1_000).toFixed(1)}K`
  return '$' + Number(v).toLocaleString('en-CA', { maximumFractionDigits: 0 })
}

function fmtPct(v) {
  if (v == null) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(1)}%`
}

function fmtDateShort(iso) {
  if (!iso) return '—'
  try { return formatDate(iso, { year: 'numeric', month: 'short', day: 'numeric' }) }
  catch { return iso }
}

function fmtMonthLabel(yyyymm) {
  if (!yyyymm) return ''
  const [y, m] = yyyymm.split('-')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${months[parseInt(m, 10) - 1]} ${y.slice(2)}`
}

function ChangeBadge({ pct, neutral = false }) {
  if (pct == null) {
    return <span className="text-xs text-gray-400">no prior</span>
  }
  if (neutral) {
    return <span className="text-xs text-gray-500">{fmtPct(pct)}</span>
  }
  const positive = pct >= 0
  return (
    <span className={`text-xs font-medium ${positive ? 'text-green-700' : 'text-red-700'}`}>
      {positive ? '▲' : '▼'} {Math.abs(pct).toFixed(1)}%
    </span>
  )
}

function Skeleton({ h = 'h-4', w = 'w-full' }) {
  return <div className={`animate-pulse bg-gray-200 rounded ${h} ${w}`} />
}

function KpiTile({ label, value, sub, change, changeUnit = 'pct' }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5">
      <p className="text-xs uppercase tracking-wider text-gray-500 font-medium">{label}</p>
      <p className="mt-2 text-3xl font-bold text-gray-900">{value}</p>
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-gray-500">{sub}</span>
        {changeUnit === 'pct'
          ? <ChangeBadge pct={change} />
          : (change != null
              ? <span className={`text-xs font-medium ${change >= 0 ? 'text-green-700' : 'text-red-700'}`}>
                  {change >= 0 ? '▲' : '▼'} {Math.abs(change)}
                </span>
              : <span className="text-xs text-gray-400">no prior</span>)}
      </div>
    </div>
  )
}

export default function Analytics() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [period, setPeriod] = useState('12m')

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(null)
    metricsApi.getSalesAnalytics(period)
      .then(res => { if (!cancelled) setData(res.data.data) })
      .catch(err => {
        if (!cancelled) setError(err.response?.data?.detail || err.message)
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [period])

  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <p className="text-red-800 font-medium mb-3">Failed to load Sales Analytics</p>
          <p className="text-red-600 text-sm mb-4">{error}</p>
          <button onClick={() => setPeriod(period)} className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm">
            Retry
          </button>
        </div>
      </div>
    )
  }

  const kpis = data?.kpis || {}
  const trend = (data?.monthly_trend || []).map(m => ({
    ...m,
    label: fmtMonthLabel(m.month),
  }))
  const quarters = data?.quarterly_summary || []
  const customers = data?.top_customers || []

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Sales Analytics</h1>
          <p className="text-sm text-gray-500 mt-1">
            Revenue, customer mix, and trend — sourced from BC posted invoices
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1 bg-gray-100 rounded-lg p-1">
          {PERIODS.map(p => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                period === p.value ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Headline KPIs */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {loading ? (
          Array(4).fill(0).map((_, i) => <Skeleton key={i} h="h-28" />)
        ) : (
          <>
            <KpiTile
              label="Revenue"
              value={fmtMoney(kpis.revenue, { compact: true })}
              sub={`Prior: ${fmtMoney(kpis.prior_revenue, { compact: true })}`}
              change={kpis.revenue_change_pct}
            />
            <KpiTile
              label="Invoices"
              value={kpis.invoice_count ?? '—'}
              sub={`Prior: ${kpis.prior_invoice_count ?? 0}`}
              change={kpis.invoice_count_change}
              changeUnit="raw"
            />
            <KpiTile
              label="Avg Invoice"
              value={fmtMoney(kpis.avg_invoice)}
              sub={`Prior: ${fmtMoney(kpis.prior_avg_invoice)}`}
              change={kpis.avg_invoice_change_pct}
            />
            <KpiTile
              label="Active Customers"
              value={kpis.active_customers ?? '—'}
              sub={`Prior: ${kpis.prior_active_customers ?? 0}`}
              change={kpis.active_customers_change}
              changeUnit="raw"
            />
          </>
        )}
      </section>

      {/* Revenue trend */}
      <section className="mb-8 bg-white rounded-lg border border-gray-200 p-5">
        <div className="flex items-baseline justify-between mb-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
              Revenue Trend
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">Last 24 months · 3-month rolling average overlay</p>
          </div>
        </div>
        {loading ? (
          <Skeleton h="h-72" />
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={trend} margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis
                yAxisId="left"
                tick={{ fontSize: 11 }}
                tickFormatter={v => v >= 1000 ? `$${(v / 1000).toFixed(0)}K` : `$${v}`}
              />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(value, name) =>
                  name === 'invoice_count'
                    ? [value, 'Invoices']
                    : ['$' + Number(value).toLocaleString('en-CA', { maximumFractionDigits: 0 }),
                       name === 'revenue' ? 'Revenue' : '3-month avg']
                }
              />
              <Bar yAxisId="left" dataKey="revenue" name="revenue" fill="#3B82F6" radius={[3, 3, 0, 0]} />
              <Line yAxisId="left" type="monotone" dataKey="rolling_3mo_avg" name="rolling_3mo_avg"
                    stroke="#10B981" strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </section>

      {/* Quarterly summary */}
      <section className="mb-8 bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
            Quarterly Summary
            <span className="ml-2 text-xs text-gray-400 font-normal normal-case">(last 8 quarters · YoY = same quarter prior year)</span>
          </h2>
        </div>
        {loading ? (
          <div className="p-5 space-y-2">{Array(4).fill(0).map((_, i) => <Skeleton key={i} h="h-8" />)}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Quarter</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Revenue</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Invoices</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Avg</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">YoY</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {quarters.map(q => (
                  <tr key={q.quarter} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-sm font-medium text-gray-900 whitespace-nowrap">{q.quarter}</td>
                    <td className="px-4 py-2 text-sm text-right text-gray-900 whitespace-nowrap font-medium">
                      {fmtMoney(q.revenue)}
                    </td>
                    <td className="px-4 py-2 text-sm text-right text-gray-700 whitespace-nowrap">{q.invoice_count}</td>
                    <td className="px-4 py-2 text-sm text-right text-gray-700 whitespace-nowrap">{fmtMoney(q.avg_invoice)}</td>
                    <td className="px-4 py-2 text-sm text-right whitespace-nowrap">
                      <ChangeBadge pct={q.yoy_change_pct} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Top customers */}
      <section className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
            Top Customers
            <span className="ml-2 text-xs text-gray-400 font-normal normal-case">
              ({kpis.label}) · compared to {kpis.prior_label || 'prior period'}
            </span>
          </h2>
          {customers.length > 0 && (
            <span className="text-xs text-gray-500">{customers.length} customers</span>
          )}
        </div>
        {loading ? (
          <div className="p-5 space-y-2">{Array(8).fill(0).map((_, i) => <Skeleton key={i} h="h-8" />)}</div>
        ) : customers.length === 0 ? (
          <div className="p-12 text-center text-gray-500 text-sm">No invoices in this period.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Customer</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Revenue</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">vs Prior</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Invoices</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Avg</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Last Invoice</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {customers.map((c, i) => (
                  <tr key={`${c.customer_no || c.customer_name}-${i}`} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-sm text-gray-900 whitespace-nowrap">
                      {c.customer_name || c.customer_no || '—'}
                      {c.customer_no && c.customer_name && (
                        <span className="text-xs text-gray-400 ml-1">#{c.customer_no}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-sm text-right text-gray-900 whitespace-nowrap font-medium">
                      {fmtMoney(c.revenue)}
                    </td>
                    <td className="px-4 py-2 text-sm text-right whitespace-nowrap">
                      {c.change_pct == null && c.prior_revenue === 0 && c.revenue > 0
                        ? <span className="text-xs text-blue-700">new</span>
                        : <ChangeBadge pct={c.change_pct} />}
                    </td>
                    <td className="px-4 py-2 text-sm text-right text-gray-700 whitespace-nowrap">{c.invoice_count}</td>
                    <td className="px-4 py-2 text-sm text-right text-gray-700 whitespace-nowrap">{fmtMoney(c.avg_invoice)}</td>
                    <td className="px-4 py-2 text-sm text-gray-600 whitespace-nowrap">{fmtDateShort(c.last_invoice_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {data?.generated_at && (
        <p className="mt-4 text-xs text-gray-400 text-right">
          Updated {new Date(data.generated_at).toLocaleString('en-CA')}
        </p>
      )}
    </div>
  )
}
