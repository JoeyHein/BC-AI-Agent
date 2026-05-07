import { useEffect, useState } from 'react'
import { metricsApi } from '../api/client'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ComposedChart, Line, CartesianGrid, Legend } from 'recharts'
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

function OpenOrdersDistribution({ scheduleChart, ageChart, scheduleBuckets, total, loading }) {
  const [view, setView] = useState('schedule')
  const data = view === 'schedule' ? scheduleChart : ageChart
  const subtitle = view === 'schedule'
    ? 'Bucketed against each order’s requested delivery date'
    : 'Bucketed by calendar age since order date'

  return (
    <section className="mb-8 bg-white rounded-lg border border-gray-200 p-5">
      <div className="flex items-baseline justify-between mb-1 gap-4 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
            Open Orders Distribution
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 bg-gray-100 rounded-md p-1">
            <button
              onClick={() => setView('schedule')}
              className={`px-3 py-1 text-xs font-medium rounded ${
                view === 'schedule'
                  ? 'bg-white shadow text-gray-900'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              By Schedule
            </button>
            <button
              onClick={() => setView('age')}
              className={`px-3 py-1 text-xs font-medium rounded ${
                view === 'age'
                  ? 'bg-white shadow text-gray-900'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              By Age
            </button>
          </div>
          <div className="text-2xl font-bold text-gray-900">{total ?? 0}</div>
        </div>
      </div>

      {/* Quick-glance summary of schedule buckets so the team sees at a glance */}
      {view === 'schedule' && !loading && (
        <div className="grid grid-cols-3 gap-3 mt-4 mb-2">
          <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2">
            <p className="text-xs uppercase text-red-700 font-medium">Late</p>
            <p className="text-xl font-bold text-red-700">{scheduleBuckets.late}</p>
          </div>
          <div className="rounded-md bg-green-50 border border-green-200 px-3 py-2">
            <p className="text-xs uppercase text-green-700 font-medium">On Time</p>
            <p className="text-xl font-bold text-green-700">{scheduleBuckets.on_time}</p>
          </div>
          <div className="rounded-md bg-blue-50 border border-blue-200 px-3 py-2">
            <p className="text-xs uppercase text-blue-700 font-medium">Early</p>
            <p className="text-xl font-bold text-blue-700">{scheduleBuckets.early}</p>
          </div>
        </div>
      )}

      {loading ? (
        <Skeleton h="h-52" />
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
            <XAxis dataKey="label" tick={{ fontSize: 12 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
            <Tooltip />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {data.map((d, i) => <Cell key={i} fill={d.color} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </section>
  )
}

const SCHEDULE_LABELS = {
  late: { text: 'Late', cls: 'bg-red-100 text-red-700' },
  on_time: { text: 'On Time', cls: 'bg-green-100 text-green-700' },
  early: { text: 'Early', cls: 'bg-blue-100 text-blue-700' },
  no_schedule: { text: 'No date', cls: 'bg-gray-100 text-gray-600' },
}

function ScheduleBadge({ status }) {
  const meta = SCHEDULE_LABELS[status] || SCHEDULE_LABELS.no_schedule
  return (
    <span className={`inline-block px-2 py-0.5 text-xs font-medium rounded ${meta.cls}`}>
      {meta.text}
    </span>
  )
}

function fmtMonthLabel(yyyymm) {
  if (!yyyymm) return ''
  // 'YYYY-MM' → 'MMM YY'
  const [y, m] = yyyymm.split('-')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${months[parseInt(m, 10) - 1]} ${y.slice(2)}`
}

function CycleTimeTrend({ trend, loading }) {
  if (!loading && (!trend || trend.length === 0)) return null
  const chart = (trend || []).map(m => ({
    month: fmtMonthLabel(m.month),
    avg_days: m.avg_days || 0,
    median_days: m.median_days || 0,
    count: m.invoice_count || 0,
  }))
  return (
    <section className="mb-8 bg-white rounded-lg border border-gray-200 p-5">
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
          12-Month Trend
          <span className="ml-2 text-xs text-gray-400 font-normal normal-case">
            (cycle time + volume)
          </span>
        </h2>
      </div>
      {loading ? (
        <Skeleton h="h-64" />
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={chart} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis yAxisId="left" tick={{ fontSize: 11 }} label={{ value: 'days', angle: -90, position: 'insideLeft', style: { fontSize: 11, fill: '#6b7280' } }} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} label={{ value: 'invoices', angle: 90, position: 'insideRight', style: { fontSize: 11, fill: '#6b7280' } }} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar yAxisId="right" dataKey="count" name="Invoices" fill="#dbeafe" />
            <Line yAxisId="left" type="monotone" dataKey="avg_days" name="Avg days" stroke="#ef4444" strokeWidth={2} dot={{ r: 3 }} />
            <Line yAxisId="left" type="monotone" dataKey="median_days" name="Median days" stroke="#10b981" strokeWidth={2} strokeDasharray="4 4" dot={{ r: 3 }} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </section>
  )
}

function CycleTimeByCustomer({ rows, loading, lookbackDays }) {
  if (!loading && (!rows || rows.length === 0)) return null
  return (
    <section className="mb-8 bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-200 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
          Slowest Customers by Avg Cycle Time
          <span className="ml-2 text-xs text-gray-400 font-normal normal-case">
            (last {lookbackDays || 90} days · ≥ 2 invoices)
          </span>
        </h2>
      </div>
      {loading ? (
        <div className="p-5 space-y-2">
          {Array(6).fill(0).map((_, i) => <Skeleton key={i} h="h-6" />)}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Customer</th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Invoices</th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Avg cycle</th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Median</th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Worst</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(rows || []).map((c, i) => (
                <tr key={`${c.customer_no || c.customer_name}-${i}`} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-sm text-gray-900 whitespace-nowrap">
                    {c.customer_name || c.customer_no || '—'}
                    {c.customer_no && c.customer_name && (
                      <span className="text-xs text-gray-400 ml-1">#{c.customer_no}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-sm text-right text-gray-700 whitespace-nowrap">{c.invoice_count}</td>
                  <td className="px-4 py-2 text-sm text-right whitespace-nowrap font-medium">
                    <span className={
                      c.avg_days > 56 ? 'text-red-700'
                      : c.avg_days > 42 ? 'text-orange-700'
                      : c.avg_days > 28 ? 'text-yellow-700'
                      : 'text-green-700'
                    }>
                      {c.avg_days}d
                    </span>
                  </td>
                  <td className="px-4 py-2 text-sm text-right text-gray-600 whitespace-nowrap">{c.median_days}d</td>
                  <td className="px-4 py-2 text-sm text-right text-gray-500 whitespace-nowrap">{c.max_days}d</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function CycleTimeSection({ cycle, loading }) {
  if (!loading && !cycle) return null
  const buckets = cycle?.buckets || { under_4w: 0, under_6w: 0, under_8w: 0, over_8w: 0 }
  const pct = cycle?.bucket_pct || { under_4w: 0, under_6w: 0, under_8w: 0, over_8w: 0 }
  const samples = cycle?.samples || []

  return (
    <section className="mb-8">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
          Order → Invoice Cycle Time
          <span className="ml-2 text-xs text-gray-400 font-normal normal-case">(closed orders)</span>
        </h2>
        {cycle && !loading && (
          <p className="text-xs text-gray-500">
            {cycle.invoice_count} invoiced in last {cycle.lookback_days} days
            {cycle.avg_days != null && ` · avg ${cycle.avg_days}d`}
            {cycle.median_days != null && ` · median ${cycle.median_days}d`}
          </p>
        )}
      </div>
      {cycle?.error && (
        <p className="text-xs text-red-600 mb-2">Cycle time unavailable: {cycle.error}</p>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        {loading ? (
          Array(4).fill(0).map((_, i) => <Skeleton key={i} h="h-24" />)
        ) : (
          <>
            <KpiTile
              label="Closed ≤ 4 weeks"
              value={pct.under_4w}
              count={buckets.under_4w}
              color={SUCCESS_BUCKET_COLORS.under_4w}
              bgClass="bg-green-50 border-green-200"
            />
            <KpiTile
              label="Closed ≤ 6 weeks"
              value={pct.under_6w}
              count={buckets.under_6w}
              color={SUCCESS_BUCKET_COLORS.under_6w}
              bgClass="bg-yellow-50 border-yellow-200"
            />
            <KpiTile
              label="Closed ≤ 8 weeks"
              value={pct.under_8w}
              count={buckets.under_8w}
              color={SUCCESS_BUCKET_COLORS.under_8w}
              bgClass="bg-orange-50 border-orange-200"
            />
            <KpiTile
              label="Over 8 weeks"
              value={pct.over_8w}
              count={buckets.over_8w}
              color={SUCCESS_BUCKET_COLORS.over_8w}
              bgClass="bg-red-50 border-red-200"
            />
          </>
        )}
      </div>
      {samples.length > 0 && (
        <details className="bg-white rounded-lg border border-gray-200">
          <summary className="px-5 py-3 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-50">
            Slowest {samples.length} orders by cycle time
          </summary>
          <div className="overflow-x-auto border-t border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Order #</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Customer</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Order Date</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Invoice Date</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Cycle</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {samples.map((s, i) => (
                  <tr key={`${s.invoice_no}-${i}`} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-sm text-gray-900 whitespace-nowrap">{s.order_no || '—'}</td>
                    <td className="px-4 py-2 text-sm text-gray-700 whitespace-nowrap">{s.customer || '—'}</td>
                    <td className="px-4 py-2 text-sm text-gray-600 whitespace-nowrap">{fmtDate(s.order_date)}</td>
                    <td className="px-4 py-2 text-sm text-gray-600 whitespace-nowrap">{fmtDate(s.invoice_date)}</td>
                    <td className="px-4 py-2 text-sm text-right whitespace-nowrap font-medium">
                      <span className={
                        s.cycle_days > 56 ? 'text-red-700'
                        : s.cycle_days > 42 ? 'text-orange-700'
                        : s.cycle_days > 28 ? 'text-yellow-700'
                        : 'text-green-700'
                      }>
                        {(s.cycle_days / 7).toFixed(1)} wks
                      </span>
                      <span className="text-gray-400 ml-1">({s.cycle_days}d)</span>
                    </td>
                    <td className="px-4 py-2 text-sm text-right text-gray-700 whitespace-nowrap">{fmtMoney(s.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  )
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

  const openRows = data?.open_orders || []
  const openSummary = data?.open_summary || { total: 0, green: 0, yellow: 0, red: 0 }

  // Two views on the open-order distribution. "Schedule" is the default
  // because it judges each order against its own requested delivery date —
  // a 9-week-old order whose customer wanted a 4-month lead time is Early,
  // not Late. "Age" is the calendar-time view and is informational.
  const scheduleBuckets = openSummary.by_schedule || { early: 0, on_time: 0, late: 0, no_schedule: 0 }
  const scheduleChart = [
    { label: 'Late',        count: scheduleBuckets.late,        color: '#EF4444' },
    { label: 'On Time',     count: scheduleBuckets.on_time,     color: '#10B981' },
    { label: 'Early',       count: scheduleBuckets.early,       color: '#3B82F6' },
    { label: 'No date',     count: scheduleBuckets.no_schedule, color: '#9CA3AF' },
  ].filter(b => b.count > 0 || b.label !== 'No date')
  const ageChart = [
    { label: 'Under 4 wks', count: openSummary.green || 0,  color: OPEN_BUCKET_COLORS.green },
    { label: '4 – 6 wks',   count: openSummary.yellow || 0, color: OPEN_BUCKET_COLORS.yellow },
    { label: 'Over 6 wks',  count: openSummary.red || 0,    color: OPEN_BUCKET_COLORS.red },
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

      {/* Order-to-invoice cycle time (closed orders, live from BC) */}
      <CycleTimeSection cycle={data?.cycle_time} loading={loading} />

      {/* 12-month trend — always 12 months regardless of selector */}
      <CycleTimeTrend trend={data?.cycle_time?.monthly_trend} loading={loading} />

      {/* Customer breakdown for the selected window */}
      <CycleTimeByCustomer
        rows={data?.cycle_time?.by_customer}
        loading={loading}
        lookbackDays={data?.cycle_time?.lookback_days}
      />

      {/* Open orders distribution — schedule view by default, age view
          is opt-in. Schedule view buckets each order against its own
          requested delivery date (Early / On Time / Late) so a long
          customer-requested lead time doesn't show up as "Late". */}
      <OpenOrdersDistribution
        scheduleChart={scheduleChart}
        ageChart={ageChart}
        scheduleBuckets={scheduleBuckets}
        total={openSummary.total}
        loading={loading}
      />

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
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Schedule</th>
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
                    <td className="px-4 py-2 text-sm whitespace-nowrap">
                      <ScheduleBadge status={o.schedule_status} />
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
