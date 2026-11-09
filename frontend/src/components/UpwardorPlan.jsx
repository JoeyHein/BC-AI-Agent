import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { upwardorPlanApi } from '../api/client'

const STATUS = {
  on_track: { label: 'On track', className: 'bg-sky-100 text-sky-900' },
  ahead: { label: 'Ahead', className: 'bg-green-100 text-green-900' },
  behind: { label: 'Behind', className: 'bg-red-100 text-red-900' },
}

const HIT = {
  hit: 'On plan',
  miss: 'Behind',
  ahead: 'Ahead',
  in_progress: 'This week',
  pending: 'Waiting',
  upcoming: 'Planned',
}

const LEVER_LABEL = {
  planned: 'Planned',
  posted: 'Posted',
  missed: 'Missed',
  in_plan: 'In the Nov 24 plan',
  moved: 'Moved to January',
  not_started: 'Not started',
  holding: 'Holding',
  released: 'Released',
  upcoming: 'In the plan',
  on_cap: 'On the cap',
  over_cap: 'Over the cap',
}

const SOURCE = {
  business_central: 'Business Central',
  business_central_excluding_tax: 'Business Central, before tax',
  business_central_vendor_ledger: 'Business Central vendor ledger',
  derived_from_balance: 'From the vendor balance',
  staff_override: 'Entered by staff',
  statement_nov_3: 'Nov 3 statement',
  week_actuals: 'Week actuals',
  unavailable: 'Not available yet',
  plan: 'Plan',
  mixed: 'Mixed sources',
  baseline: 'Plan',
  baseline_nov_2026: 'Nov 2026 baseline',
  actuals: 'Posted actuals',
  staff: 'Set by an admin',
}

function money(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const amount = Math.round(Number(value))
  const text = Math.abs(amount).toLocaleString('en-CA')
  return amount < 0 ? `-$${text}` : `$${text}`
}

function signed(value, digits = true) {
  if (value == null) return '—'
  const amount = Math.round(Number(value))
  if (!digits) return money(amount)
  const text = Math.abs(amount).toLocaleString('en-CA')
  if (amount > 0) return `+$${text}`
  if (amount < 0) return `-$${text}`
  return '$0'
}

function sourceLabel(key) {
  return SOURCE[key] || key || '—'
}

function balanceCaption(data) {
  const source = data?.current_balance_source
  if (source === 'business_central') {
    const when = formatAsOf(data.balance_as_of || data.as_of)
    return when ? `Business Central, as of ${when}` : 'Business Central'
  }
  if (source === 'statement_nov_3') return 'Nov 3 statement — Business Central unavailable'
  return sourceLabel(source)
}

function formatAsOf(iso) {
  if (!iso) return ''
  const [day, rest] = String(iso).split('T')
  const [year, month, date] = day.split('-')
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const time = (rest || '').slice(0, 5)
  return `${months[Number(month) - 1]} ${Number(date)}, ${year}${time ? `, ${time}` : ''} MT`
}

function favorableClass(value, favorableWhen) {
  if (value == null || Math.round(Number(value)) === 0) return 'text-gray-500'
  const good = favorableWhen === 'positive' ? value > 0 : value < 0
  return good ? 'text-green-700' : 'text-red-700'
}

function StatusPill({ status }) {
  const tone = STATUS[status] || STATUS.on_track
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-sm font-semibold ${tone.className}`}>
      {tone.label}
    </span>
  )
}

function Card({ title, value, sub, children }) {
  return (
    <div className="bg-white shadow rounded-lg p-5">
      <p className="text-sm text-gray-500">{title}</p>
      <p className="mt-1 text-2xl font-bold text-gray-900">{value}</p>
      {sub && <p className="mt-1 text-xs text-gray-500">{sub}</p>}
      {children}
    </div>
  )
}

function ChartTip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-md border border-gray-200 bg-white px-3 py-2 text-xs shadow">
      <p className="font-medium text-gray-800 mb-1">Week of {label}</p>
      {payload.map((item) => (
        <p key={item.dataKey} style={{ color: item.color }}>
          {item.name}: {money(item.value)}
        </p>
      ))}
    </div>
  )
}

export default function UpwardorPlan() {
  const queryClient = useQueryClient()
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['upwardor-plan'],
    queryFn: async () => (await upwardorPlanApi.get()).data,
    staleTime: 60_000,
  })

  const save = useMutation({
    mutationFn: async ({ kind, body }) => {
      const response = kind === 'actuals'
        ? await upwardorPlanApi.updateActuals(body)
        : await upwardorPlanApi.updateLever(body)
      return response.data
    },
    onSuccess: (next) => {
      queryClient.setQueryData(['upwardor-plan'], next)
    },
  })

  if (isLoading) {
    return <div className="p-6 text-gray-500">Loading the Upwardor plan…</div>
  }
  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        {error.response?.data?.detail || error.message}
      </div>
    )
  }

  const gap = data.gap_to_target
  const christmasGap = data.live_christmas - data.target
  const christmasText = christmasGap > 0
    ? `${money(christmasGap)} above $500K`
    : `${money(Math.abs(christmasGap))} under $500K`
  const bannerClass = data.ahead_on_both
    ? 'border-green-200 bg-green-50 text-green-900'
    : data.status === 'behind'
      ? 'border-red-200 bg-red-50 text-red-900'
      : 'border-gray-200 bg-white text-gray-800'

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-gray-500">
            Get the Upward Door payable balance under $500,000 by the week of Dec 22.
          </p>
          <p className="mt-1 text-xs text-gray-400">
            As of {formatAsOf(data.as_of)}. Each week is the seven days from the date shown. {data.timezone}.
            {' '}Balance: {balanceCaption(data)}. Invoices: {sourceLabel(data.sources?.invoices)}. Payments: {sourceLabel(data.sources?.payments)}.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <div className={`rounded-lg border px-4 py-3 text-sm ${bannerClass}`}>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={data.status} />
          <span>{data.reforecast_note}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <Card
          title="Upwardor balance"
          value={money(data.current_balance)}
          sub={balanceCaption(data)}
        />
        <Card
          title="Gap to $500K"
          value={money(Math.abs(gap))}
          sub={gap > 0 ? 'Above $500K today' : gap < 0 ? 'Under $500K today' : 'At $500K today'}
        />
        <Card
          title="Christmas projection"
          value={money(data.live_christmas)}
          sub={`${christmasText} · plan ${money(data.plan_christmas)} · status quo ${money(data.status_quo_christmas)}`}
        >
          {data.stretch_christmas !== data.live_christmas && (
            <p className="mt-1 text-xs text-gray-500">
              Stretch, counting only favorable weeks: {money(data.stretch_christmas)}
            </p>
          )}
        </Card>
        <Card title="Versus the plan" value={STATUS[data.status]?.label || data.status} sub={
          data.status_vs_target === 'under'
            ? 'Live path is at or under $500K by Christmas'
            : 'Live path is still over $500K at Christmas'
        }>
          <div className="mt-2">
            <StatusPill status={data.status} />
          </div>
        </Card>
      </div>

      {(data.sources?.notes?.length > 0 || data.sources?.errors?.length > 0) && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          <p className="font-medium">Where these numbers come from</p>
          <ul className="mt-1 list-disc pl-5 space-y-1">
            {(data.sources.notes || []).map((note) => <li key={note}>{note}</li>)}
            {(data.sources.errors || []).map((note) => <li key={note}>{note}</li>)}
          </ul>
          <p className="mt-2 text-xs text-amber-900">
            Balance: {balanceCaption(data)}. Invoices: {sourceLabel(data.sources.invoices)}. Payments: {sourceLabel(data.sources.payments)}.
          </p>
        </div>
      )}

      <ThisWeek week={data.this_week} reduced={data.targets_auto_reduced} reduction={data.invoice_target_reduction} />

      <div className="bg-white shadow rounded-lg p-5">
        <h2 className="text-sm font-medium text-gray-700">Balance path</h2>
        <p className="mt-1 text-xs text-gray-500">
          Actual balance so far, the live projection, the static plan, the do-nothing path, and the $500K line.
        </p>
        <div className="mt-4 h-80">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data.chart} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="week" tick={{ fontSize: 12 }} />
              <YAxis tickFormatter={(value) => money(value)} tick={{ fontSize: 12 }} width={72} />
              <Tooltip content={<ChartTip />} />
              <Legend />
              <ReferenceLine y={data.target} stroke="#DC2626" strokeDasharray="4 4" label={{ value: '$500K', fill: '#DC2626', fontSize: 12 }} />
              <Line type="monotone" dataKey="actual" name="Actual" stroke="#111827" strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} />
              <Line type="monotone" dataKey="live" name="Live projection" stroke="#059669" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="plan" name="Plan" stroke="#4F46E5" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="status_quo" name="Status quo" stroke="#9CA3AF" strokeDasharray="4 4" dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      <WeekTable weeks={data.weeks} />
      <Levers
        levers={data.levers}
        orders={data.purchase_orders}
        canEdit={data.can_edit}
        saving={save.isPending}
        onSave={(body) => save.mutate({ kind: 'lever', body })}
      />
      {data.can_edit && (
        <ActualsForm
          weeks={data.weeks}
          saving={save.isPending}
          error={save.error}
          onSave={(body) => save.mutate({ kind: 'actuals', body })}
        />
      )}
      <p className="text-xs text-gray-400">
        Opening balance {money(data.opening_balance)}. {data.opening_note} Plan pays Upwardor {money(data.plan_payments_total)} and expects {money(data.plan_invoices_total)} of new invoices. Moving GNB PO-001066 to January, by itself, projects {money(data.gnb_christmas)}.
      </p>
    </div>
  )
}

function ThisWeek({ week, reduced, reduction }) {
  if (!week) return null
  return (
    <div className="bg-white shadow rounded-lg p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-gray-700">Week of {week.label}</h2>
        <span className="text-xs font-medium text-gray-500">{HIT[week.hit] || week.hit}</span>
      </div>
      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        <Compare
          title="Payments to Upwardor"
          planned={week.planned_payments}
          actual={week.actual_payments}
          forecast={week.payment_forecast}
          variance={week.payment_variance}
          favorable="positive"
          source={week.payment_source}
          remaining={week.remaining_payments}
          remainingLabel="Still to pay this week"
        />
        <Compare
          title="New Upwardor invoices"
          planned={week.planned_invoices}
          actual={week.actual_invoices}
          forecast={week.invoice_forecast}
          variance={week.invoice_variance}
          favorable="negative"
          source={week.invoice_source}
          remaining={week.remaining_invoices}
          remainingLabel="Still expected this week"
        />
      </div>
      <p className="mt-4 text-sm text-gray-600">
        Week versus plan: <span className={favorableClass(week.variance, 'negative')}>{signed(week.variance)}</span>
        {' '}on the balance. Negative means the balance is lower than the plan.
        {week.target_reduced && ' This week’s remaining invoice target was cut because purchasing is below the pace expected so far.'}
        {reduced && ` Invoice targets still ahead were reduced by ${money(reduction)}.`}
      </p>
    </div>
  )
}

function Compare({ title, planned, actual, forecast, variance, favorable, source, remaining, remainingLabel }) {
  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <p className="text-sm font-medium text-gray-800">{title}</p>
      <dl className="mt-3 grid grid-cols-2 gap-y-2 text-sm">
        <dt className="text-gray-500">Plan</dt>
        <dd className="text-right font-medium text-gray-900">{money(planned)}</dd>
        <dt className="text-gray-500">Actual</dt>
        <dd className="text-right font-medium text-gray-900">{money(actual)}</dd>
        <dt className="text-gray-500">Variance</dt>
        <dd className={`text-right font-medium ${favorableClass(variance, favorable)}`}>{signed(variance)}</dd>
        <dt className="text-gray-500">Week forecast</dt>
        <dd className="text-right text-gray-900">{money(forecast)}</dd>
        <dt className="text-gray-500">{remainingLabel}</dt>
        <dd className="text-right text-gray-900">{money(remaining)}</dd>
      </dl>
      <p className="mt-2 text-xs text-gray-400">{sourceLabel(source)}</p>
    </div>
  )
}

function WeekTable({ weeks }) {
  return (
    <div className="bg-white shadow rounded-lg">
      <div className="px-5 py-4 border-b border-gray-200">
        <h2 className="text-sm font-medium text-gray-700">Week by week</h2>
        <p className="mt-1 text-xs text-gray-500">
          Collections are the cash the plan uses for the sweep. They do not change the payable balance. The adjusted invoice target is the buy ceiling after any underspend.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {['Week', 'Collections', 'Invoices plan', 'Invoices actual', 'Invoice ceiling', 'Payments plan', 'Payments actual', 'Plan end', 'Live end', 'Vs plan', ''].map((heading) => (
                <th key={heading || 'result'} className="px-3 py-3 text-right first:text-left text-xs font-medium uppercase tracking-wide text-gray-500 whitespace-nowrap">
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {weeks.map((week) => (
              <tr key={week.week_of} className={week.state === 'open' ? 'bg-sky-50' : undefined}>
                <td className="px-3 py-3 text-left font-medium text-gray-900 whitespace-nowrap">{week.label}</td>
                <td className="px-3 py-3 text-right text-gray-600">{money(week.collections)}</td>
                <td className="px-3 py-3 text-right text-gray-900">{money(week.planned_invoices)}</td>
                <td className={`px-3 py-3 text-right ${favorableClass(week.invoice_delta, 'negative')}`}>{money(week.actual_invoices)}</td>
                <td className="px-3 py-3 text-right text-gray-900">
                  {week.state === 'closed' ? '—' : money(week.adjusted_invoice_target)}
                  {week.state !== 'closed' && week.target_auto_reduced && <span className="ml-1 text-xs text-green-700">reduced</span>}
                </td>
                <td className="px-3 py-3 text-right text-gray-900">{money(week.planned_payments)}</td>
                <td className={`px-3 py-3 text-right ${favorableClass(week.payment_delta, 'positive')}`}>{money(week.actual_payments)}</td>
                <td className="px-3 py-3 text-right text-gray-600">{money(week.plan_end)}</td>
                <td className="px-3 py-3 text-right font-medium text-gray-900">{money(week.live_end)}</td>
                <td className={`px-3 py-3 text-right ${favorableClass(week.state === 'future' ? null : week.variance, 'negative')}`}>
                  {week.state === 'future' && !week.variance ? '—' : signed(week.variance)}
                </td>
                <td className="px-3 py-3 text-right text-gray-700 whitespace-nowrap">{HIT[week.hit] || week.hit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Levers({ levers, orders, canEdit, saving, onSave }) {
  return (
    <div className="bg-white shadow rounded-lg">
      <div className="px-5 py-4 border-b border-gray-200">
        <h2 className="text-sm font-medium text-gray-700">Plan levers</h2>
        <p className="mt-1 text-xs text-gray-500">
          Status only. {canEdit ? 'Admins can update these.' : 'An admin can update these.'}
        </p>
      </div>
      <ul className="divide-y divide-gray-100">
        {(levers || []).map((lever) => (
          <li key={lever.id} className="px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900">{lever.title}</p>
                <p className="mt-1 text-sm text-gray-600">{lever.detail}</p>
                {lever.note && <p className="mt-1 text-xs text-gray-500">Note: {lever.note}</p>}
                <p className="mt-1 text-xs text-gray-400">{sourceLabel(lever.source)}</p>
              </div>
              {canEdit && lever.options?.length > 0 ? (
                <select
                  aria-label={`${lever.title} status`}
                  value={lever.status}
                  disabled={saving}
                  onChange={(event) => onSave({ id: lever.id, status: event.target.value })}
                  className="rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-800"
                >
                  {lever.options.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              ) : (
                <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-semibold text-gray-700">
                  {LEVER_LABEL[lever.status] || lever.status}
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
      {orders?.length > 0 && (
        <div className="border-t border-gray-100 px-5 py-4">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Open Upwardor POs</p>
          <ul className="mt-2 space-y-1 text-sm text-gray-700">
            {orders.slice(0, 8).map((order) => (
              <li key={order.number}>
                {order.number} · {order.status} · {money(order.amount)}
                {order.requested_receipt_date ? ` · receipt ${order.requested_receipt_date}` : ''}
                {order.is_gnb ? ' · GNB' : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function ActualsForm({ weeks, saving, error, onSave }) {
  const [weekOf, setWeekOf] = useState(weeks.find((week) => week.state === 'open')?.week_of || weeks[0].week_of)
  const [invoices, setInvoices] = useState('')
  const [payments, setPayments] = useState('')
  const [credits, setCredits] = useState('')

  const submit = (event) => {
    event.preventDefault()
    const body = { week_of: weekOf }
    if (invoices !== '') body.invoices = Number(invoices)
    if (payments !== '') body.payments = Number(payments)
    if (credits !== '') body.credits = Number(credits)
    onSave(body)
  }

  return (
    <form onSubmit={submit} className="bg-white shadow rounded-lg p-5">
      <h2 className="text-sm font-medium text-gray-700">Record a week</h2>
      <p className="mt-1 text-sm text-gray-500">
        Use this when Business Central does not have the figure. A number here covers the live feed for that week. Leave a box blank to keep the current source.
      </p>
      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <label className="text-sm text-gray-600">
          Week
          <select value={weekOf} onChange={(event) => setWeekOf(event.target.value)} className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5">
            {weeks.map((week) => (
              <option key={week.week_of} value={week.week_of}>{week.label}</option>
            ))}
          </select>
        </label>
        <NumberField label="Invoices" value={invoices} onChange={setInvoices} />
        <NumberField label="Payments" value={payments} onChange={setPayments} />
        <NumberField label="Credits" value={credits} onChange={setCredits} />
      </div>
      {error && (
        <p className="mt-3 text-sm text-red-700">{error.response?.data?.detail || error.message}</p>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="submit" disabled={saving} className="rounded-md bg-odc-800 px-3 py-2 text-sm font-medium text-white hover:bg-odc-900 disabled:opacity-60">
          Save week
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => onSave({ week_of: weekOf, clear: true })}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Clear staff figures
        </button>
      </div>
    </form>
  )
}

function NumberField({ label, value, onChange }) {
  return (
    <label className="text-sm text-gray-600">
      {label}
      <input
        inputMode="decimal"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5"
        placeholder="Leave blank"
      />
    </label>
  )
}
