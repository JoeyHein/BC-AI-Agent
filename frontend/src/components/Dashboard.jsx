import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { kpiApi } from '../api/client'
import { useAuth } from '../contexts/AuthContext'

const HELP = {
  soToPo: 'Average days from the sales order date to the day the purchase order was sent. The sent date is the portal email time when that was recorded, otherwise the purchase order date once the order is open.',
  ack: 'Average days from the sent date to the Upwardor acknowledgement. A promised receipt date in Business Central is not an acknowledgement.',
  unacked: 'Purchase orders that have been sent, are not fully received, and have no Upwardor acknowledgement. This is the open list as of the snapshot, not only this month.',
  onTime: 'Share of purchase orders whose first receipt in the month was on or before the required receipt date.',
  sales: 'Posted sales invoices before tax. The arrows compare the same days of the prior month, and the same dates last year.',
  week: 'Posted sales invoices in the week that contains the last day of this snapshot, compared with the week before.',
  quotes: 'Orders in the month whose external document is a quote that is no longer open, divided by those orders plus quotes still open from the same dates. The open amount is every quote still in Business Central.',
  margin: 'Invoice amount before tax, minus quantity times the unit cost on the item card. Orders under the cutoff in the product-line file are flagged.',
  variance: 'Posted purchase invoice total minus the purchase order total, before tax.',
  ar: 'Customer-card balances. The bar splits open sales invoices by due date. Deposits are open customer payments when Business Central returns that list.',
  backlog: 'Open sales orders, the part not yet shipped, before tax.',
  ship: 'Days from the sales order date to the shipment date.',
  inventory: 'Quantity on hand times the item unit cost.',
  reorder: 'Items whose quantity on hand is under the reorder point, when Business Central includes that field.',
  freight: 'Invoice lines that match the freight words in the product-line file, divided by sales before tax.',
  gauge: 'The gauge is the average sales-order to purchase-order days. The count is orders over the late-day line.',
  vendorBars: 'Average acknowledgement days by vendor. The dashed line is the late-day cutoff.',
  trend: 'Posted sales invoices. Weekly is kept for the open month. Last year is the same week or the same month.',
  mix: 'Invoice lines grouped into commercial, residential, and aluminum from the product-line list. Anything else is Other.',
  brands: 'Invoice lines that name LiftMaster, Micanan or McKinnon, or Guardian. The arrow is the change versus the same days of the prior month.',
  marginBars: 'Gross margin percent by product line. The dashed line is the low-margin cutoff.',
}

const TONE = {
  good: { bar: 'bg-emerald-500', text: 'text-emerald-700', pill: 'bg-emerald-100 text-emerald-800', dot: 'bg-emerald-500', fill: '#059669' },
  warn: { bar: 'bg-amber-500', text: 'text-amber-700', pill: 'bg-amber-100 text-amber-800', dot: 'bg-amber-500', fill: '#d97706' },
  bad: { bar: 'bg-red-500', text: 'text-red-700', pill: 'bg-red-100 text-red-800', dot: 'bg-red-500', fill: '#dc2626' },
  neutral: { bar: 'bg-slate-300', text: 'text-slate-900', pill: 'bg-slate-100 text-slate-600', dot: 'bg-slate-400', fill: '#64748b' },
}

const STATUS_LABEL = { good: 'On track', warn: 'Watch', bad: 'Attention' }

const SLICE = {
  commercial: '#0C2340',
  residential: '#3b82c4',
  aluminum: '#14b8a6',
  other: '#cbd5e1',
  liftmaster: '#c2410c',
  mckinnon: '#1e3a5f',
  guardian: '#059669',
}

const AGING = {
  current: '#059669',
  '1_30': '#0C2340',
  '31_60': '#f59e0b',
  '61_90': '#ea580c',
  over_90: '#dc2626',
}

const TIP = { borderRadius: 12, border: '1px solid #e5e7eb', fontSize: 12, boxShadow: '0 8px 24px rgba(15, 23, 42, 0.08)' }

function money(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return new Intl.NumberFormat('en-CA', {
    style: 'currency', currency: 'CAD', minimumFractionDigits: 0, maximumFractionDigits: 0,
  }).format(value)
}

function moneyExact(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD' }).format(value)
}

function moneyShort(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return ''
  if (Math.abs(n) >= 1000) return `$${Math.round(n / 1000)}k`
  return `$${Math.round(n)}`
}

function daysLabel(value) {
  if (value == null) return '—'
  return Number(value).toFixed(1)
}

function pctLabel(value) {
  if (value == null) return '—'
  return `${Number(value).toFixed(1)}%`
}

function toneOf(status) {
  return TONE[status] || TONE.neutral
}

function fillOf(status) {
  return toneOf(status).fill
}

function noteState(coverage, id) {
  return (coverage || []).find((note) => note.id === id)?.state
}

function Trend({ delta, kind = 'upGood', compact = false, suffix = 'vs prior' }) {
  if (delta == null || Number.isNaN(Number(delta))) return null
  const value = Number(delta)
  const up = value > 0
  const flat = value === 0
  const favorable = flat || (kind === 'upGood' ? up : !up)
  const color = flat ? 'text-gray-500' : favorable ? 'text-emerald-700' : 'text-red-700'
  const arrow = flat ? '→' : up ? '↑' : '↓'
  return (
    <span className={`inline-flex items-center gap-0.5 text-sm font-semibold tabular-nums ${color}`}>
      <span aria-hidden="true">{arrow}</span>
      <span>{Math.abs(value).toFixed(1)}%{compact ? '' : ` ${suffix}`}</span>
    </span>
  )
}

function HelpTip({ text }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  return (
    <span className="inline-flex flex-col items-end">
      <button
        type="button"
        aria-expanded={open}
        aria-label="How this is calculated"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold text-gray-400 ring-1 ring-gray-200 hover:bg-gray-50"
      >
        i
      </button>
      {open && (
        <span className="mt-1 max-w-[16rem] rounded-xl bg-odc-900 px-3 py-2 text-left text-xs font-normal normal-case leading-snug tracking-normal text-white shadow-lg">
          {text}
        </span>
      )}
    </span>
  )
}

function StatusMark({ status }) {
  const label = STATUS_LABEL[status]
  if (!label) return null
  const tone = toneOf(status)
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone.pill}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
      {label}
    </span>
  )
}

function PartialMark({ flag }) {
  if (!flag || flag === 'ok') return null
  const label = flag === 'missing' ? 'Unavailable' : 'Partial'
  return (
    <span title={label} aria-label={label} className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-100 text-xs font-bold text-amber-700">
      !
    </span>
  )
}

function KpiTile({ label, value, unit, delta, deltaSuffix = 'vs prior', deltaKind, yearAgo, status, flag, sub, help }) {
  const tone = toneOf(status)
  return (
    <article className="relative min-w-0 rounded-2xl bg-white p-3.5 shadow-sm ring-1 ring-gray-200 sm:p-5">
      <div className={`absolute inset-y-0 left-0 w-1.5 rounded-l-2xl ${tone.bar}`} />
      <div className="flex items-start justify-between gap-2 pl-2">
        <p className="min-w-0 truncate text-[11px] font-semibold uppercase tracking-wide text-gray-500 sm:text-xs">{label}</p>
        <span className="flex items-center gap-1">
          <PartialMark flag={flag} />
          <StatusMark status={status} />
          <HelpTip text={help} />
        </span>
      </div>
      <p className={`mt-2 pl-2 text-3xl font-semibold leading-none tracking-tight tabular-nums sm:text-4xl ${tone.text}`}>
        {value}
        {unit && value !== '—' && <span className="ml-1 text-sm font-medium text-gray-400">{unit}</span>}
      </p>
      {(delta != null || yearAgo != null || sub) && (
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-0.5 pl-2">
          <Trend delta={delta} kind={deltaKind} suffix={deltaSuffix} />
          <Trend delta={yearAgo} suffix="vs last year" />
          {sub && <p className="text-sm font-medium text-gray-500">{sub}</p>}
        </div>
      )}
    </article>
  )
}

function Section({ title, children }) {
  return (
    <section className="space-y-3">
      <h2 className="px-0.5 text-xs font-semibold uppercase tracking-[0.14em] text-odc-800">{title}</h2>
      {children}
    </section>
  )
}

function ChartCard({ title, action, help, children, className = '' }) {
  return (
    <div className={`min-w-0 rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-200 sm:p-5 ${className}`}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        <span className="flex items-center gap-2">
          {action}
          <HelpTip text={help} />
        </span>
      </div>
      {children}
    </div>
  )
}

function EmptyChart({ label = 'Nothing in this range' }) {
  return <p className="flex h-36 items-center justify-center text-sm text-gray-400">{label}</p>
}

function Details({ title, count, children }) {
  return (
    <details className="group rounded-2xl bg-white shadow-sm ring-1 ring-gray-200">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 px-4 py-3 text-sm font-medium text-gray-800 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 flex-1">{title}</span>
        {count != null && (
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-semibold tabular-nums text-gray-600">{count}</span>
        )}
        <svg className="h-4 w-4 shrink-0 text-gray-400 transition-transform group-open:rotate-180" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </summary>
      <div className="border-t border-gray-100">{children}</div>
    </details>
  )
}

function Table({ columns, rows, rowClass }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
            {columns.map((column) => (
              <th key={column.key} className={`px-3 py-2 font-medium ${column.align === 'right' ? 'text-right' : ''}`}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td className="px-3 py-4 text-gray-400" colSpan={columns.length}>Nothing in this date range.</td>
            </tr>
          )}
          {rows.map((row, index) => (
            <tr key={row.key || index} className={`border-b border-gray-100 ${rowClass ? rowClass(row) : ''}`}>
              {columns.map((column) => (
                <td key={column.key} className={`px-3 py-2 ${column.align === 'right' ? 'text-right tabular-nums' : ''}`}>
                  {column.render ? column.render(row) : row[column.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DaysGauge({ days, status, max }) {
  const scale = max || 10
  const clamped = days == null ? 0 : Math.max(0, Math.min(Number(days), scale))
  const rest = Math.max(scale - clamped, 0)
  return (
    <div className="relative h-36 sm:h-40">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={[
              { name: 'days', value: clamped || 0.0001 },
              { name: 'rest', value: rest || 0.0001 },
            ]}
            cy="100%"
            startAngle={180}
            endAngle={0}
            innerRadius="72%"
            outerRadius="100%"
            dataKey="value"
            stroke="none"
            isAnimationActive={false}
          >
            <Cell fill={days == null ? '#e5e7eb' : fillOf(status)} />
            <Cell fill="#e5e7eb" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 text-center">
        <p className={`text-3xl font-semibold leading-none tabular-nums sm:text-4xl ${toneOf(status).text}`}>
          {daysLabel(days)}
        </p>
        <p className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">days</p>
      </div>
    </div>
  )
}

function VendorAckChart({ vendors, lateDays }) {
  const rows = [...(vendors || [])].sort((a, b) => (b.average_days || 0) - (a.average_days || 0))
  if (rows.length === 0) return <EmptyChart label="No acknowledgements in this range" />
  return (
    <div style={{ height: Math.max(132, rows.length * 52) }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 36, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e5e7eb" />
          <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
          <YAxis
            type="category"
            dataKey="vendor_name"
            width={96}
            tick={{ fontSize: 11, fill: '#334155' }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(value) => (String(value).length > 14 ? `${String(value).slice(0, 13)}…` : value)}
          />
          <Tooltip
            contentStyle={TIP}
            formatter={(value) => [`${Number(value).toFixed(1)} days`, 'Average']}
          />
          <ReferenceLine x={lateDays} stroke="#dc2626" strokeDasharray="4 4" />
          <Bar dataKey="average_days" radius={[0, 6, 6, 0]} barSize={16} isAnimationActive={false}>
            {rows.map((row) => (
              <Cell key={row.vendor_number} fill={fillOf(row.status)} />
            ))}
            <LabelList dataKey="average_days" position="right" formatter={(value) => Number(value).toFixed(1)} style={{ fontSize: 11, fill: '#334155' }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function Purchasing({ data, coverage, lateDays }) {
  const card = data?.so_to_po || {}
  const acks = data?.acknowledgements || {}
  const unacked = data?.unacknowledged || {}
  const onTime = data?.on_time || {}
  const late = card.late_count || 0
  return (
    <Section title="Purchasing">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <KpiTile label="SO to PO" value={daysLabel(card.average_days)} unit="days" status={card.status} flag={noteState(coverage, 'so_to_po')} help={HELP.soToPo} />
        <KpiTile label="Vendor ack" value={daysLabel(acks.average_days)} unit="days" status={acks.status} flag={noteState(coverage, 'po_ack')} help={HELP.ack} />
        <KpiTile label="Unacked POs" value={unacked.count == null ? '—' : unacked.count} status={unacked.status} flag={noteState(coverage, 'unacknowledged')} help={HELP.unacked} />
        <KpiTile label="On time" value={pctLabel(onTime.rate_pct)} status={onTime.status} flag={noteState(coverage, 'vendor_ontime')} help={HELP.onTime} />
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
        <ChartCard title="SO to PO" className="lg:col-span-2" help={HELP.gauge}>
          <div className="flex items-end gap-3">
            <div className="min-w-0 flex-1">
              <DaysGauge days={card.average_days} status={card.status} max={Math.max(lateDays * 2, 10)} />
            </div>
            <div className={`mb-1 flex w-[5.75rem] shrink-0 flex-col items-center justify-center rounded-2xl px-2 py-4 sm:w-28 ${late > 0 ? 'bg-red-50' : 'bg-emerald-50'}`}>
              <p className={`text-4xl font-semibold leading-none tabular-nums ${late > 0 ? 'text-red-600' : 'text-emerald-700'}`}>{late}</p>
              <p className={`mt-2 text-center text-[11px] font-semibold uppercase leading-tight tracking-wide ${late > 0 ? 'text-red-700' : 'text-emerald-800'}`}>
                over {lateDays} days
              </p>
            </div>
          </div>
        </ChartCard>
        <ChartCard title="Vendor acknowledgement days" className="lg:col-span-3" help={HELP.vendorBars}>
          <VendorAckChart vendors={acks.vendors} lateDays={lateDays} />
        </ChartCard>
      </div>

      <div className="space-y-2">
        <Details title="Sales orders and purchase orders" count={(card.pairs || []).length}>
          <Table
            columns={[
              { key: 'sales_order', label: 'Sales order' },
              { key: 'sales_order_date', label: 'SO date' },
              { key: 'customer', label: 'Customer' },
              { key: 'purchase_order', label: 'Purchase order' },
              { key: 'vendor_name', label: 'Vendor' },
              { key: 'po_sent_date', label: 'PO sent', render: (row) => row.po_sent_date || 'Not sent' },
              { key: 'source', label: 'Sent date from', render: (row) => row.sent_source === 'portal_email' ? 'Email sent' : row.sent_source === 'bc_order_date' ? 'PO date' : '—' },
              { key: 'days', label: 'Days', align: 'right', render: (row) => row.days == null ? `${row.age_days} open` : row.days },
            ]}
            rows={(card.pairs || []).map((row) => ({ ...row, key: `${row.sales_order}-${row.purchase_order}` }))}
            rowClass={(row) => (row.highlight ? 'bg-red-50 text-red-900' : '')}
          />
          {card.sales_orders_without_po > 0 && (
            <p className="px-3 py-3 text-xs text-gray-500">
              {card.sales_orders_without_po} sales order{card.sales_orders_without_po === 1 ? '' : 's'} in this range with no linked purchase order.
            </p>
          )}
        </Details>
        <Details title="Acknowledgement and on-time by vendor" count={(acks.vendors || []).length + (onTime.vendors || []).length}>
          <p className="px-3 pt-3 text-xs font-semibold uppercase tracking-wide text-gray-400">Acknowledgement days</p>
          <Table
            columns={[
              { key: 'vendor_name', label: 'Vendor' },
              { key: 'count', label: 'POs', align: 'right' },
              { key: 'average_days', label: 'Avg days', align: 'right' },
            ]}
            rows={(acks.vendors || []).map((row) => ({ ...row, key: row.vendor_number }))}
            rowClass={(row) => (row.status === 'bad' ? 'bg-red-50' : row.status === 'warn' ? 'bg-amber-50' : '')}
          />
          <p className="px-3 pt-3 text-xs font-semibold uppercase tracking-wide text-gray-400">On time</p>
          <Table
            columns={[
              { key: 'vendor_name', label: 'Vendor' },
              { key: 'rate', label: 'On time', align: 'right', render: (row) => pctLabel(row.rate_pct) },
              { key: 'late', label: 'Late', align: 'right' },
            ]}
            rows={(onTime.vendors || []).map((row) => ({ ...row, key: `ot-${row.vendor_number}` }))}
            rowClass={(row) => (row.status === 'bad' ? 'bg-red-50' : row.status === 'warn' ? 'bg-amber-50' : '')}
          />
        </Details>
        <Details title="Unacknowledged purchase orders" count={unacked.count || 0}>
          {(unacked.vendors || []).length === 0 && <p className="px-4 py-4 text-sm text-gray-400">No sent purchase orders are waiting on an acknowledgement.</p>}
          {(unacked.vendors || []).map((vendor) => (
            <div key={vendor.vendor_number} className="border-t border-gray-100 first:border-t-0">
              <div className="flex items-center justify-between px-4 py-2">
                <p className="text-sm font-medium text-gray-800">{vendor.vendor_name}</p>
                <p className="text-xs text-gray-500">{vendor.count} open · oldest {vendor.oldest_days} days</p>
              </div>
              <Table
                columns={[
                  { key: 'number', label: 'PO' },
                  { key: 'sent_date', label: 'Sent' },
                  { key: 'age_days', label: 'Age (days)', align: 'right' },
                  { key: 'amount', label: 'Amount', align: 'right', render: (row) => moneyExact(row.amount) },
                ]}
                rows={(vendor.purchase_orders || []).map((row) => ({ ...row, key: row.number }))}
                rowClass={(row) => (row.status === 'bad' ? 'bg-red-50' : row.status === 'warn' ? 'bg-amber-50' : '')}
              />
            </div>
          ))}
        </Details>
      </div>
    </Section>
  )
}

function SliceLegend({ rows, deltaKey }) {
  return (
    <ul className="mt-2 space-y-1.5">
      {rows.map((row) => (
        <li key={row.id} className="flex items-center gap-2 text-sm">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: row.fill }} />
          <span className="min-w-0 flex-1 truncate text-gray-700">{row.label}</span>
          <span className="shrink-0 font-semibold tabular-nums text-gray-900">{money(row.amount)}</span>
          {deltaKey && <Trend delta={row[deltaKey]} compact />}
        </li>
      ))}
    </ul>
  )
}

function Donut({ slices }) {
  const drawn = slices.filter((row) => Number(row.amount) > 0)
  if (drawn.length === 0) return <EmptyChart label="No sales in this range" />
  return (
    <div className="h-52 sm:h-60">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={drawn} dataKey="amount" nameKey="label" innerRadius="58%" outerRadius="86%" paddingAngle={2} stroke="none">
            {drawn.map((row) => (
              <Cell key={row.id} fill={row.fill} />
            ))}
          </Pie>
          <Tooltip contentStyle={TIP} formatter={(value, name) => [money(value), name]} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

function SalesTrend({ weekly, monthly, defaultGrain = 'week' }) {
  const [grain, setGrain] = useState(defaultGrain)
  const series = grain === 'week' ? weekly : monthly
  const toggle = (
    <div className="inline-flex rounded-full bg-gray-100 p-0.5">
      {[{ id: 'week', label: 'Weekly' }, { id: 'month', label: 'Monthly' }].map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => setGrain(option.id)}
          className={`min-h-9 rounded-full px-3 text-xs font-semibold ${grain === option.id ? 'bg-white text-odc-900 shadow-sm' : 'text-gray-500'}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
  return (
    <ChartCard title="Sales trend" action={toggle} help={HELP.trend}>
      {series.length === 0 ? <EmptyChart /> : (
        <div className="h-56 sm:h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} minTickGap={28} />
              <YAxis tickFormatter={moneyShort} tick={{ fontSize: 11, fill: '#64748b' }} width={44} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={TIP} formatter={(value, name) => [money(value), name]} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="amount" name="Sales" stroke="#0C2340" strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} connectNulls />
              <Line type="monotone" dataKey="year_ago_amount" name="Last year" stroke="#94a3b8" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  )
}

function Sales({ data, coverage, showWeek = true }) {
  const mix = data?.product_mix || {}
  const mixRows = [
    ...(mix.lines || []).map((line) => ({ ...line, fill: SLICE[line.id] || '#94a3b8' })),
    ...(mix.other_amount ? [{ id: 'other', label: 'Other', amount: mix.other_amount, fill: SLICE.other }] : []),
  ]
  const brands = (data?.operators?.brands || []).map((row) => ({ ...row, fill: SLICE[row.id] || '#94a3b8' }))
  const movers = ['commercial', 'residential', 'aluminum'].flatMap((id) => {
    const line = (mix.lines || []).find((row) => row.id === id)
    return ((mix.top_movers || {})[id] || []).map((row) => ({
      ...row,
      key: `${id}-${row.item_number}`,
      line: line?.label || id,
    }))
  })
  return (
    <Section title="Sales">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <KpiTile
          label="Sales"
          value={money(data?.month?.amount ?? data?.range_total?.amount)}
          delta={data?.month?.prior_delta_pct}
          deltaSuffix="vs prior month"
          yearAgo={data?.month?.year_ago_delta_pct}
          status={data?.month?.status}
          flag={noteState(coverage, 'sales')}
          help={HELP.sales}
        />
        {showWeek && (
          <KpiTile
            label={data?.week?.label || 'This week'}
            value={money(data?.week?.amount)}
            delta={data?.week?.prior_delta_pct}
            deltaSuffix="vs prior week"
            status={data?.week?.status}
            flag={noteState(coverage, 'sales')}
            help={HELP.week}
          />
        )}
        <KpiTile
          label="Quotes won"
          value={pctLabel(data?.quotes?.conversion_pct)}
          status={data?.quotes?.status}
          flag={noteState(coverage, 'quotes')}
          sub={data?.quotes?.open_quote_value != null ? `${money(data.quotes.open_quote_value)} open` : null}
          help={HELP.quotes}
        />
      </div>

      <SalesTrend
        key={showWeek ? 'week' : 'month'}
        weekly={data?.weekly_series || []}
        monthly={data?.monthly_series || []}
        defaultGrain={showWeek ? 'week' : 'month'}
      />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <ChartCard title="Product mix" help={HELP.mix}>
          <Donut slices={mixRows} />
          <SliceLegend rows={mixRows} />
        </ChartCard>
        <ChartCard title="Operator brands" help={HELP.brands}>
          <Donut slices={brands} />
          <SliceLegend rows={brands} deltaKey="delta_pct" />
        </ChartCard>
      </div>

      <Details title="Top movers" count={movers.length}>
        <Table
          columns={[
            { key: 'line', label: 'Line' },
            { key: 'item_number', label: 'Item' },
            { key: 'description', label: 'Name' },
            { key: 'amount', label: 'Sales', align: 'right', render: (row) => moneyExact(row.amount) },
            { key: 'delta', label: 'Change', align: 'right', render: (row) => moneyExact(row.delta) },
          ]}
          rows={movers}
          rowClass={(row) => (row.delta < 0 ? 'bg-red-50' : '')}
        />
      </Details>
    </Section>
  )
}

function Financial({ data, coverage }) {
  const margin = data?.margin || {}
  const variance = data?.po_variance || {}
  const ar = data?.ar || {}
  const backlog = data?.backlog || {}
  const buckets = ar.buckets || []
  const agingRow = { name: 'AR' }
  buckets.forEach((bucket) => { agingRow[bucket.id] = bucket.amount || 0 })
  const agingTotal = buckets.reduce((sum, bucket) => sum + (Number(bucket.amount) || 0), 0)
  const lines = margin.by_line || []
  return (
    <Section title="Financial">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <KpiTile label="Margin" value={pctLabel(margin.margin_pct)} status={margin.status} flag={noteState(coverage, 'margin')} sub={margin.margin_amount != null ? money(margin.margin_amount) : null} help={HELP.margin} />
        <KpiTile label="Invoice vs PO" value={moneyExact(variance.variance_amount)} status={variance.status} flag={noteState(coverage, 'po_variance')} help={HELP.variance} />
        <KpiTile label="Receivable" value={money(ar.total)} status={ar.status} flag={noteState(coverage, 'ar')} sub={ar.customer_count ? `${ar.customer_count} customers` : null} help={HELP.ar} />
        <KpiTile label="Backlog" value={money(backlog.amount)} status={backlog.status} flag={noteState(coverage, 'backlog')} sub={backlog.order_count ? `${backlog.order_count} orders` : null} help={HELP.backlog} />
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <ChartCard title="AR aging" help={HELP.ar}>
          {agingTotal <= 0 ? <EmptyChart label="No open receivables" /> : (
            <div className="h-24">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart layout="vertical" data={[agingRow]} margin={{ top: 12, right: 8, left: 0, bottom: 8 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="name" hide />
                  <Tooltip contentStyle={TIP} formatter={(value, name) => [money(value), name]} />
                  {buckets.map((bucket) => (
                    <Bar key={bucket.id} dataKey={bucket.id} stackId="aging" fill={AGING[bucket.id] || '#94a3b8'} name={bucket.label} barSize={28} isAnimationActive={false} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <ul className="mt-1 flex flex-wrap gap-2">
            {buckets.map((bucket) => (
              <li key={bucket.id} className="inline-flex items-center gap-1.5 rounded-full bg-gray-50 px-2.5 py-1 text-xs">
                <span className="h-2 w-2 rounded-full" style={{ background: AGING[bucket.id] || '#94a3b8' }} />
                <span className="text-gray-500">{bucket.label}</span>
                <span className="font-semibold tabular-nums text-gray-900">{money(bucket.amount)}</span>
              </li>
            ))}
          </ul>
          {(ar.deposits?.amount != null || ar.credit_balances) && (
            <p className="mt-3 text-sm font-medium text-gray-500">
              {ar.deposits?.amount != null ? `Deposits ${money(ar.deposits.amount)}` : ''}
              {ar.deposits?.amount != null && ar.credit_balances ? ' · ' : ''}
              {ar.credit_balances ? `Credits ${money(ar.credit_balances)}` : ''}
            </p>
          )}
        </ChartCard>
        <ChartCard title="Margin by product line" help={HELP.marginBars}>
          {lines.length === 0 ? <EmptyChart /> : (
            <div className="h-56 sm:h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={lines} margin={{ top: 18, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(value) => `${value}%`} tick={{ fontSize: 11, fill: '#64748b' }} width={40} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={TIP} formatter={(value) => [pctLabel(value), 'Margin']} />
                  {margin.threshold_pct != null && <ReferenceLine y={margin.threshold_pct} stroke="#d97706" strokeDasharray="4 4" />}
                  <Bar dataKey="margin_pct" radius={[6, 6, 0, 0]} barSize={36} isAnimationActive={false}>
                    {lines.map((row) => (
                      <Cell key={row.id} fill={fillOf(row.status)} />
                    ))}
                    <LabelList dataKey="margin_pct" position="top" formatter={(value) => (value == null ? '' : `${Number(value).toFixed(0)}%`)} style={{ fontSize: 11, fill: '#334155' }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>
      </div>

      <div className="space-y-2">
        <Details title="Low-margin orders" count={(margin.low_margin_orders || []).length}>
          <Table
            columns={[
              { key: 'invoice', label: 'Invoice' },
              { key: 'customer', label: 'Customer' },
              { key: 'sales', label: 'Sales', align: 'right', render: (row) => moneyExact(row.sales) },
              { key: 'cost', label: 'Cost', align: 'right', render: (row) => moneyExact(row.cost) },
              { key: 'margin_pct', label: 'Margin', align: 'right', render: (row) => pctLabel(row.margin_pct) },
            ]}
            rows={(margin.low_margin_orders || []).map((row) => ({ ...row, key: row.invoice }))}
            rowClass={() => 'bg-red-50'}
          />
        </Details>
        <Details title="Purchase invoice difference by vendor" count={(variance.vendors || []).length}>
          <Table
            columns={[
              { key: 'vendor_name', label: 'Vendor' },
              { key: 'variance_amount', label: 'Difference', align: 'right', render: (row) => moneyExact(row.variance_amount) },
              { key: 'missing_po_count', label: 'No PO total', align: 'right' },
            ]}
            rows={(variance.vendors || []).map((row) => ({ ...row, key: row.vendor_number }))}
            rowClass={(row) => (row.status === 'bad' ? 'bg-red-50' : row.status === 'warn' ? 'bg-amber-50' : '')}
          />
        </Details>
      </div>
    </Section>
  )
}

function Operations({ data, coverage }) {
  const ship = data?.order_to_ship || {}
  const inventory = data?.inventory || {}
  const freight = data?.freight || {}
  const reorderKnown = inventory.reorder_state === 'ok'
  const below = inventory.below_reorder_count || 0
  return (
    <Section title="Operations">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <KpiTile label="Order to ship" value={daysLabel(ship.average_days)} unit="days" status={ship.status} flag={noteState(coverage, 'order_to_ship')} help={HELP.ship} />
        <KpiTile
          label="Inventory"
          value={money(inventory.value)}
          status="neutral"
          flag={noteState(coverage, 'inventory')}
          sub={inventory.item_count ? `${inventory.item_count} items` : null}
          help={HELP.inventory}
        />
        <KpiTile
          label="Below reorder"
          value={reorderKnown ? below : '—'}
          status={!reorderKnown ? 'neutral' : (below > 0 ? 'bad' : 'good')}
          flag={reorderKnown ? null : 'partial'}
          help={HELP.reorder}
        />
        <KpiTile label="Freight" value={pctLabel(freight.percent)} status={freight.status} flag={noteState(coverage, 'freight')} sub={freight.amount != null ? money(freight.amount) : null} help={HELP.freight} />
      </div>
      <div className="space-y-2">
        <Details title="Slow movers" count={inventory.slow_count || 0}>
          <Table
            columns={[
              { key: 'item_number', label: 'Item' },
              { key: 'description', label: 'Name' },
              { key: 'on_hand', label: 'On hand', align: 'right' },
              { key: 'value', label: 'Value', align: 'right', render: (row) => money(row.value) },
            ]}
            rows={(inventory.slow_movers || []).map((row) => ({ ...row, key: row.item_number }))}
          />
        </Details>
        <Details title="Below reorder point" count={reorderKnown ? below : null}>
          {!reorderKnown && (
            <p className="px-4 py-3 text-sm text-amber-800">Reorder point is not available from Business Central.</p>
          )}
          <Table
            columns={[
              { key: 'item_number', label: 'Item' },
              { key: 'on_hand', label: 'On hand', align: 'right' },
              { key: 'reorder_point', label: 'Reorder', align: 'right' },
              { key: 'shortfall', label: 'Short', align: 'right' },
            ]}
            rows={(inventory.below_reorder || []).map((row) => ({ ...row, key: row.item_number }))}
            rowClass={() => 'bg-red-50'}
          />
        </Details>
      </div>
    </Section>
  )
}

function Dashboard() {
  const { isAdmin } = useAuth()
  const [month, setMonth] = useState('')
  const [recalcError, setRecalcError] = useState('')

  const query = useQuery({
    queryKey: ['kpi-dashboard', month],
    queryFn: async () => (await kpiApi.dashboard({ month: month || undefined })).data,
    refetchInterval: (q) => (q.state.data?.snapshot?.status === 'running' ? 4000 : false),
  })

  const snapshot = query.data?.snapshot
  const selected = month || snapshot?.month || ''
  const running = snapshot?.status === 'running'
  const showWeek = snapshot ? snapshot.weekly !== false && snapshot.frozen !== true : true
  const hasSections = Boolean(query.data?.sections)
  const coverage = query.data?.coverage || []
  const attention = coverage.filter((note) => note.state === 'partial' || note.state === 'missing')
  const lateDays = query.data?.thresholds?.so_to_po_late_days ?? 5

  async function recalculate() {
    setRecalcError('')
    try {
      await kpiApi.recalculate({ month: selected || undefined })
      query.refetch()
    } catch (error) {
      setRecalcError(error?.response?.data?.detail || 'Recalculate could not start.')
    }
  }

  return (
    <div className="space-y-8 px-3 pb-10 sm:px-0">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-xl font-semibold tracking-tight text-gray-900 sm:text-2xl">KPI dashboard</h1>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
            <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-500" />On track</span>
            <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-500" />Watch</span>
            <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-500" />Attention</span>
          </div>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
          <label className="text-xs font-medium text-gray-500">
            Month
            <input
              type="month"
              value={selected}
              max={snapshot?.current_month || undefined}
              onChange={(event) => setMonth(event.target.value)}
              className="mt-1 block min-h-11 w-full rounded-lg border border-gray-300 bg-white px-3 text-base text-gray-900 sm:w-44 sm:text-sm"
            />
          </label>
          {isAdmin && (
            <button
              type="button"
              onClick={recalculate}
              disabled={running}
              className="min-h-11 rounded-lg bg-odc-900 px-4 text-sm font-medium text-white disabled:opacity-60"
            >
              {running ? 'Calculating…' : 'Recalculate now'}
            </button>
          )}
          <div className="text-sm text-gray-500 sm:mb-2">
            {snapshot?.as_of_label && <p>{snapshot.as_of_label}</p>}
            {snapshot?.period_start && (
              <p>
                {snapshot.period_start} to {snapshot.period_end}
                {snapshot.frozen ? ' · closed month' : ' · month to date'}
              </p>
            )}
            {running && <p className="font-medium text-odc-800">Calculating in the background. The numbers will update when it finishes.</p>}
          </div>
        </div>
        {recalcError && <p className="text-sm text-red-700">{recalcError}</p>}
      </div>

      {query.isLoading && (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-28 animate-pulse rounded-2xl bg-white ring-1 ring-gray-200" />
          ))}
        </div>
      )}
      {query.isError && (
        <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {query.error?.response?.data?.detail || 'The KPI dashboard could not be loaded.'}
        </p>
      )}

      {query.data && !hasSections && (
        <div className="rounded-2xl bg-white px-4 py-8 text-center ring-1 ring-gray-200">
          <p className="text-sm font-medium text-gray-900">
            {snapshot?.status === 'failed'
              ? 'This month could not be calculated.'
              : running
                ? 'Calculating this month.'
                : 'This month has not been calculated yet.'}
          </p>
          <p className="mt-1 text-sm text-gray-500">
            {snapshot?.error || 'The nightly job stores the numbers. An admin can calculate this month now.'}
          </p>
        </div>
      )}

      {hasSections && (
        <>
          <Purchasing data={query.data.sections?.purchasing} coverage={coverage} lateDays={lateDays} />
          <Sales data={query.data.sections?.sales} coverage={coverage} showWeek={showWeek} />
          <Financial data={query.data.sections?.financial} coverage={coverage} />
          <Operations data={query.data.sections?.operations} coverage={coverage} />
          {attention.length > 0 && (
            <details className="group rounded-2xl border border-amber-200 bg-amber-50">
              <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 px-4 py-3 text-sm font-medium text-amber-950 [&::-webkit-details-marker]:hidden">
                <span className="min-w-0 flex-1">Data notes</span>
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900">{attention.length}</span>
                <svg className="h-4 w-4 shrink-0 text-amber-700 transition-transform group-open:rotate-180" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
                </svg>
              </summary>
              <ul className="space-y-3 border-t border-amber-200 px-4 py-3">
                {attention.map((note) => (
                  <li key={note.id}>
                    <p className="text-sm font-medium text-amber-950">
                      {note.title}
                      <span className="ml-2 text-xs font-normal uppercase">{note.state === 'missing' ? 'unavailable' : 'partial'}</span>
                    </p>
                    <p className="text-sm text-amber-900">{note.detail}</p>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  )
}

export default Dashboard
