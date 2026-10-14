import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { kpiApi } from '../api/client'

const TONE = {
  good: { bar: 'border-emerald-500', text: 'text-emerald-700', pill: 'bg-emerald-100 text-emerald-800' },
  warn: { bar: 'border-amber-500', text: 'text-amber-700', pill: 'bg-amber-100 text-amber-800' },
  bad: { bar: 'border-red-500', text: 'text-red-700', pill: 'bg-red-100 text-red-800' },
  neutral: { bar: 'border-slate-300', text: 'text-slate-800', pill: 'bg-slate-100 text-slate-600' },
}

function formatDay(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function lastDays(count) {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - (count - 1))
  return { from: formatDay(start), to: formatDay(end) }
}

function thisMonth() {
  const end = new Date()
  const start = new Date(end.getFullYear(), end.getMonth(), 1)
  return { from: formatDay(start), to: formatDay(end) }
}

function lastMonth() {
  const today = new Date()
  const start = new Date(today.getFullYear(), today.getMonth() - 1, 1)
  const end = new Date(today.getFullYear(), today.getMonth(), 0)
  return { from: formatDay(start), to: formatDay(end) }
}

function thisYear() {
  const end = new Date()
  const start = new Date(end.getFullYear(), 0, 1)
  return { from: formatDay(start), to: formatDay(end) }
}

const PRESETS = [
  { id: '7', label: 'Last 7 days', range: () => lastDays(7) },
  { id: '30', label: 'Last 30 days', range: () => lastDays(30) },
  { id: 'month', label: 'This month', range: thisMonth },
  { id: 'last', label: 'Last month', range: lastMonth },
  { id: 'year', label: 'This year', range: thisYear },
]

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

function daysLabel(value) {
  if (value == null) return '—'
  return `${Number(value).toFixed(1)} days`
}

function pctLabel(value) {
  if (value == null) return '—'
  return `${Number(value).toFixed(1)}%`
}

function signedPct(value) {
  if (value == null) return 'No comparison'
  const arrow = value > 0 ? '▲' : value < 0 ? '▼' : '•'
  return `${arrow} ${Math.abs(value).toFixed(1)}% vs prior`
}

function toneOf(status) {
  return TONE[status] || TONE.neutral
}

function Card({ title, value, detail, status, flag }) {
  const tone = toneOf(status)
  return (
    <div className={`bg-white rounded-lg shadow-sm border border-gray-200 border-l-4 ${tone.bar} p-4`}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-gray-500">{title}</p>
        {flag && flag !== 'ok' && (
          <span className="shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800">
            {flag === 'missing' ? 'Unavailable' : 'Partial'}
          </span>
        )}
      </div>
      <p className={`mt-1 text-2xl font-semibold ${tone.text}`}>{value}</p>
      {detail && <p className="mt-1 text-xs text-gray-500">{detail}</p>}
    </div>
  )
}

function Section({ title, lede, children }) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
        {lede && <p className="text-sm text-gray-500">{lede}</p>}
      </div>
      {children}
    </section>
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

function Panel({ title, children }) {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200">
      <div className="border-b border-gray-100 px-4 py-3 text-sm font-medium text-gray-800">{title}</div>
      {children}
    </div>
  )
}

function noteState(coverage, id) {
  return coverage.find((note) => note.id === id)?.state
}

function Purchasing({ data, coverage }) {
  const card = data?.so_to_po || {}
  const acks = data?.acknowledgements || {}
  const unacked = data?.unacknowledged || {}
  const onTime = data?.on_time || {}
  return (
    <Section title="Purchasing and vendors" lede="How fast orders go out to vendors, and whether vendors confirm and deliver on time.">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card
          title="SO to PO sent"
          value={daysLabel(card.average_days)}
          detail={`${card.sent_count || 0} sent · ${card.late_count || 0} over 5 days`}
          status={card.status}
          flag={noteState(coverage, 'so_to_po')}
        />
        <Card
          title="PO to acknowledgement"
          value={daysLabel(acks.average_days)}
          detail="Average days, all vendors with an acknowledgement"
          status={acks.status}
          flag={noteState(coverage, 'po_ack')}
        />
        <Card
          title="Unacknowledged POs"
          value={unacked.count == null ? '—' : unacked.count}
          detail="Open now, any age"
          status={unacked.status}
          flag={noteState(coverage, 'unacknowledged')}
        />
        <Card
          title="Vendor on-time"
          value={pctLabel(onTime.rate_pct)}
          detail={`${onTime.on_time || 0} on time · ${onTime.late || 0} late · ${onTime.unknown || 0} unknown`}
          status={onTime.status}
          flag={noteState(coverage, 'vendor_ontime')}
        />
      </div>

      <Panel title="Every sales order and purchase order pair">
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
          <p className="px-4 py-3 text-xs text-gray-500">
            {card.sales_orders_without_po} sales order{card.sales_orders_without_po === 1 ? '' : 's'} in this range {card.sales_orders_without_po === 1 ? 'has' : 'have'} no linked purchase order.
          </p>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Acknowledgement days by vendor">
          <Table
            columns={[
              { key: 'vendor_name', label: 'Vendor' },
              { key: 'count', label: 'POs', align: 'right' },
              { key: 'average_days', label: 'Avg days', align: 'right' },
            ]}
            rows={(acks.vendors || []).map((row) => ({ ...row, key: row.vendor_number }))}
            rowClass={(row) => (row.status === 'bad' ? 'bg-red-50' : row.status === 'warn' ? 'bg-amber-50' : '')}
          />
        </Panel>
        <Panel title="On-time rate by vendor">
          <Table
            columns={[
              { key: 'vendor_name', label: 'Vendor' },
              { key: 'rate', label: 'On time', align: 'right', render: (row) => pctLabel(row.rate_pct) },
              { key: 'late', label: 'Late', align: 'right' },
            ]}
            rows={(onTime.vendors || []).map((row) => ({ ...row, key: row.vendor_number }))}
            rowClass={(row) => (row.status === 'bad' ? 'bg-red-50' : row.status === 'warn' ? 'bg-amber-50' : '')}
          />
        </Panel>
      </div>

      <Panel title="Unacknowledged purchase orders">
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
      </Panel>
    </Section>
  )
}

function Sales({ data, coverage }) {
  const weekly = data?.weekly_series || []
  const mix = data?.product_mix || {}
  return (
    <Section title="Sales" lede="Posted invoices, before tax.">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card title="Sales in this range" value={money(data?.range_total?.amount)} detail={signedPct(data?.range_total?.prior_delta_pct)} status={data?.range_total?.status} flag={noteState(coverage, 'sales')} />
        <Card title={data?.week?.label || 'This week'} value={money(data?.week?.amount)} detail={`${signedPct(data?.week?.prior_delta_pct)} · last year ${money(data?.week?.year_ago_amount)}`} status={data?.week?.status} flag={noteState(coverage, 'sales')} />
        <Card title={data?.month?.label || 'This month'} value={money(data?.month?.amount)} detail={`${signedPct(data?.month?.prior_delta_pct)} · last year ${money(data?.month?.year_ago_amount)}`} status={data?.month?.status} flag={noteState(coverage, 'sales')} />
        <Card title="Quote conversion" value={pctLabel(data?.quotes?.conversion_pct)} detail={`Open quotes ${money(data?.quotes?.open_quote_value)} · ${data?.quotes?.open_quote_count || 0} still open`} status={data?.quotes?.status} flag={noteState(coverage, 'quotes')} />
      </div>

      <Panel title="Weekly sales">
        <div className="h-64 p-2">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={weekly}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 12 }} />
              <YAxis tickFormatter={(value) => money(value)} tick={{ fontSize: 12 }} width={70} />
              <Tooltip formatter={(value) => money(value)} />
              <Legend />
              <Bar dataKey="amount" name="This period" fill="#0f766e" />
              <Bar dataKey="year_ago_amount" name="Same week last year" fill="#cbd5e1" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Product mix">
          <div className="space-y-3 p-4">
            {(mix.lines || []).map((line) => (
              <div key={line.id}>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-700">{line.label}</span>
                  <span className="tabular-nums text-gray-900">{money(line.amount)} · {pctLabel(line.share_pct)}</span>
                </div>
                <div className="mt-1 h-2 rounded bg-gray-100">
                  <div className="h-2 rounded bg-teal-700" style={{ width: `${Math.min(line.share_pct || 0, 100)}%` }} />
                </div>
              </div>
            ))}
            <p className="text-sm text-gray-500">Other (not mapped): {money(mix.other_amount)}</p>
          </div>
        </Panel>
        <Panel title="Operator sales">
          <Table
            columns={[
              { key: 'label', label: 'Brand' },
              { key: 'amount', label: 'Sales', align: 'right', render: (row) => money(row.amount) },
              { key: 'prior_amount', label: 'Prior period', align: 'right', render: (row) => money(row.prior_amount) },
            ]}
            rows={(data?.operators?.brands || []).map((row) => ({ ...row, key: row.id }))}
          />
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {['commercial', 'residential', 'aluminum'].map((id) => {
          const line = (mix.lines || []).find((row) => row.id === id)
          const movers = (mix.top_movers || {})[id] || []
          return (
            <Panel key={id} title={`Top movers · ${line?.label || id}`}>
              <Table
                columns={[
                  { key: 'item_number', label: 'Item' },
                  { key: 'delta', label: 'Change', align: 'right', render: (row) => moneyExact(row.delta) },
                ]}
                rows={movers.map((row) => ({ ...row, key: row.item_number }))}
                rowClass={(row) => (row.delta < 0 ? 'bg-red-50' : '')}
              />
            </Panel>
          )
        })}
      </div>
    </Section>
  )
}

function Financial({ data, coverage }) {
  const margin = data?.margin || {}
  const variance = data?.po_variance || {}
  const ar = data?.ar || {}
  const backlog = data?.backlog || {}
  return (
    <Section title="Financial" lede="Margin, purchase-invoice differences, what customers owe, and orders not yet shipped.">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card title="Gross margin" value={pctLabel(margin.margin_pct)} detail={`${money(margin.margin_amount)} on ${money(margin.sales)} · under ${margin.threshold_pct ?? 20}% is flagged`} status={margin.status} flag={noteState(coverage, 'margin')} />
        <Card title="Invoice vs PO" value={moneyExact(variance.variance_amount)} detail={`${variance.compared_count || 0} compared · ${variance.missing_po_count || 0} missing a PO total`} status={variance.status} flag={noteState(coverage, 'po_variance')} />
        <Card title="Accounts receivable" value={money(ar.total)} detail={`${ar.customer_count || 0} customers with a balance`} status={ar.status} flag={noteState(coverage, 'ar')} />
        <Card title="Open order backlog" value={money(backlog.amount)} detail={`${backlog.order_count || 0} orders not fully shipped`} status={backlog.status} flag={noteState(coverage, 'backlog')} />
      </div>

      <Panel title="Low-margin orders">
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
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Margin by product line">
          <Table
            columns={[
              { key: 'label', label: 'Line' },
              { key: 'margin_pct', label: 'Margin', align: 'right', render: (row) => pctLabel(row.margin_pct) },
              { key: 'sales', label: 'Sales', align: 'right', render: (row) => money(row.sales) },
            ]}
            rows={(margin.by_line || []).map((row) => ({ ...row, key: row.id }))}
            rowClass={(row) => (row.status === 'bad' ? 'bg-red-50' : row.status === 'warn' ? 'bg-amber-50' : '')}
          />
        </Panel>
        <Panel title="Purchase invoice difference by vendor">
          <Table
            columns={[
              { key: 'vendor_name', label: 'Vendor' },
              { key: 'variance_amount', label: 'Difference', align: 'right', render: (row) => moneyExact(row.variance_amount) },
              { key: 'missing_po_count', label: 'No PO total', align: 'right' },
            ]}
            rows={(variance.vendors || []).map((row) => ({ ...row, key: row.vendor_number }))}
            rowClass={(row) => (row.status === 'bad' ? 'bg-red-50' : row.status === 'warn' ? 'bg-amber-50' : '')}
          />
        </Panel>
      </div>

      <Panel title="AR aging">
        <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-5">
          {(ar.buckets || []).map((bucket) => (
            <div key={bucket.id} className={`rounded border px-3 py-2 ${bucket.status === 'bad' ? 'border-red-200 bg-red-50' : bucket.status === 'warn' ? 'border-amber-200 bg-amber-50' : 'border-gray-200'}`}>
              <p className="text-xs text-gray-500">{bucket.label}</p>
              <p className="text-lg font-semibold text-gray-900">{money(bucket.amount)}</p>
            </div>
          ))}
        </div>
        <p className="px-4 pb-4 text-xs text-gray-500">
          Deposits and prepayments: {ar.deposits?.amount == null ? 'not available from Business Central' : money(ar.deposits.amount)}.
          {ar.credit_balances ? ` Credit balances on customer cards: ${money(ar.credit_balances)}.` : ''}
        </p>
      </Panel>
    </Section>
  )
}

function Operations({ data, coverage }) {
  const ship = data?.order_to_ship || {}
  const inventory = data?.inventory || {}
  const freight = data?.freight || {}
  return (
    <Section title="Operations" lede="How long orders take to ship, what is sitting in stock, and freight against sales.">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Card title="Order to ship" value={daysLabel(ship.average_days)} detail={`${ship.with_order_date || 0} shipments with an order date · ${ship.missing_order_date || 0} without`} status={ship.status} flag={noteState(coverage, 'order_to_ship')} />
        <Card title="Inventory value" value={money(inventory.value)} detail={`${inventory.item_count || 0} items in stock · ${inventory.slow_count || 0} slow movers`} status={inventory.status} flag={noteState(coverage, 'inventory')} />
        <Card title="Freight % of sales" value={pctLabel(freight.percent)} detail={`${money(freight.amount)} freight on ${money(freight.sales)} sales`} status={freight.status} flag={noteState(coverage, 'freight')} />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Slow movers">
          <Table
            columns={[
              { key: 'item_number', label: 'Item' },
              { key: 'description', label: 'Name' },
              { key: 'on_hand', label: 'On hand', align: 'right' },
              { key: 'value', label: 'Value', align: 'right', render: (row) => money(row.value) },
            ]}
            rows={(inventory.slow_movers || []).map((row) => ({ ...row, key: row.item_number }))}
          />
        </Panel>
        <Panel title="Below reorder point">
          {inventory.reorder_state !== 'ok' && (
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
        </Panel>
      </div>
    </Section>
  )
}

function Dashboard() {
  const initial = useMemo(() => lastDays(30), [])
  const [preset, setPreset] = useState('30')
  const [range, setRange] = useState(initial)
  const [refreshTick, setRefreshTick] = useState(0)

  const query = useQuery({
    queryKey: ['kpi-dashboard', range.from, range.to, refreshTick],
    queryFn: async () => {
      const response = await kpiApi.dashboard({ from: range.from, to: range.to, refresh: refreshTick > 0 })
      return response.data
    },
  })

  const coverage = query.data?.coverage || []
  const attention = coverage.filter((note) => note.state === 'partial' || note.state === 'missing')

  function applyPreset(item) {
    setPreset(item.id)
    setRange(item.range())
    setRefreshTick(0)
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">KPI dashboard</h1>
          <p className="mt-1 text-sm text-gray-500">
            Figures come from Business Central. Green is on track, amber needs a look, red needs attention.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {PRESETS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => applyPreset(item)}
              className={`rounded-full px-3 py-1 text-sm ${preset === item.id ? 'bg-teal-800 text-white' : 'bg-white text-gray-700 border border-gray-300'}`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm text-gray-600">
          From
          <input
            type="date"
            value={range.from}
            onChange={(event) => { setPreset('custom'); setRange({ ...range, from: event.target.value }); setRefreshTick(0) }}
            className="mt-1 block rounded border border-gray-300 px-2 py-1"
          />
        </label>
        <label className="text-sm text-gray-600">
          To
          <input
            type="date"
            value={range.to}
            onChange={(event) => { setPreset('custom'); setRange({ ...range, to: event.target.value }); setRefreshTick(0) }}
            className="mt-1 block rounded border border-gray-300 px-2 py-1"
          />
        </label>
        <button
          type="button"
          onClick={() => setRefreshTick((value) => value + 1)}
          className="rounded bg-white px-3 py-2 text-sm text-gray-700 border border-gray-300"
        >
          Refresh
        </button>
        {query.data?.cached && <span className="text-xs text-gray-400">Cached for about 10 minutes</span>}
      </div>

      {query.isLoading && <p className="text-sm text-gray-500">Loading KPI dashboard…</p>}
      {query.isError && (
        <p className="rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {query.error?.response?.data?.detail || 'The KPI dashboard could not be loaded.'}
        </p>
      )}

      {query.data && (
        <>
          <details className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
            <summary className="cursor-pointer text-sm font-medium text-amber-950">
              Data notes ({attention.length})
            </summary>
            <ul className="mt-3 space-y-3">
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

          <Purchasing data={query.data.sections?.purchasing} coverage={coverage} />
          <Sales data={query.data.sections?.sales} coverage={coverage} />
          <Financial data={query.data.sections?.financial} coverage={coverage} />
          <Operations data={query.data.sections?.operations} coverage={coverage} />
        </>
      )}
    </div>
  )
}

export default Dashboard
