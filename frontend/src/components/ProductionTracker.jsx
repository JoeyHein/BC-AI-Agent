import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { opsApi } from '../api/client'
import { ActivityLog } from './Purchasing/ActivityLog'

const TABS = [
  ['tracker', 'Orders'],
  ['pos', 'Purchase orders'],
  ['todo', 'To-do'],
  ['approvals', 'Approvals'],
  ['week', 'This week'],
]

function detailOf(error, fallback) {
  return error?.response?.data?.detail || fallback
}

function Pill({ children, tone = 'gray' }) {
  const tones = {
    gray: 'bg-gray-100 text-gray-700',
    red: 'bg-red-100 text-red-800',
    amber: 'bg-amber-100 text-amber-900',
    green: 'bg-emerald-100 text-emerald-800',
    blue: 'bg-blue-100 text-blue-800',
  }
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone] || tones.gray}`}>{children}</span>
}

function PoStack({ pos }) {
  if (!pos.length) return <span className="text-gray-400">No PO</span>
  return (
    <div className="space-y-2">
      {pos.map((po) => (
        <div key={po.po_number} className="rounded-md bg-gray-50 px-2 py-1 text-xs">
          <div className="font-medium text-gray-900">{po.po_number} · {po.vendor_name || po.vendor_number || 'Vendor'}</div>
          <div className="text-gray-600">{po.lifecycle_label || po.status || '—'}</div>
          <div className="text-gray-600">Ack {po.vendor_order_no || '—'} · {po.expected_date || 'no date'}</div>
          <Communications rows={po.communications || []} />
        </div>
      ))}
    </div>
  )
}

function Communications({ rows }) {
  if (!rows.length) return null
  return (
    <details className="mt-1">
      <summary className="cursor-pointer text-odc-800">Communications ({rows.length})</summary>
      <ol className="mt-1 space-y-1">
        {rows.map((row) => (
          <li key={row.id}>
            <span className="text-gray-500">{(row.created_at || '').replace('T', ' ').slice(0, 16)} · {row.event_type}</span>
            <div>{row.body}</div>
            {row.needs_review && <span className="text-amber-800">Needs review ({row.confidence || 'low'})</span>}
            {row.web_link && <a className="ml-1 text-odc-800 underline" href={row.web_link}>Open message</a>}
            {row.attachment_name && <span className="ml-1 text-gray-500">{row.attachment_name}</span>}
          </li>
        ))}
      </ol>
    </details>
  )
}

function Select({ label, value, options, onChange }) {
  return (
    <select
      aria-label={label}
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value)}
      className="max-w-[10.5rem] rounded-md border border-gray-300 bg-white px-1.5 py-1 text-xs text-gray-900"
    >
      {options.map((option) => {
        const optionValue = typeof option === 'string' ? option : option.value
        const optionLabel = typeof option === 'string' ? (option || '—') : option.label
        return <option key={optionValue || 'blank'} value={optionValue}>{optionLabel}</option>
      })}
    </select>
  )
}

function ProductionTracker() {
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'tracker'
  const [filters, setFilters] = useState({ q: '', customer: '', status: '', supplier: '', at_risk: false, po_status: '' })
  const [expanded, setExpanded] = useState(null)
  const [banner, setBanner] = useState('')

  const tracker = useQuery({
    queryKey: ['ops-tracker', filters],
    queryFn: async () => (await opsApi.tracker({
      q: filters.q || undefined,
      customer: filters.customer || undefined,
      status: filters.status || undefined,
      supplier: filters.supplier || undefined,
      at_risk: filters.at_risk || undefined,
      po_status: filters.po_status || undefined,
    })).data,
  })

  const actions = useQuery({
    queryKey: ['ops-actions'],
    queryFn: async () => (await opsApi.actions('open')).data,
    enabled: tab === 'todo',
  })
  const messages = useQuery({
    queryKey: ['ops-messages', 'pending'],
    queryFn: async () => (await opsApi.messages('pending')).data,
    enabled: tab === 'approvals' || tab === 'tracker',
  })
  const weekly = useQuery({
    queryKey: ['ops-weekly'],
    queryFn: async () => (await opsApi.weekly()).data,
    enabled: tab === 'week',
  })

  function refreshAll() {
    queryClient.invalidateQueries({ queryKey: ['ops-tracker'] })
    queryClient.invalidateQueries({ queryKey: ['ops-actions'] })
    queryClient.invalidateQueries({ queryKey: ['ops-messages'] })
    queryClient.invalidateQueries({ queryKey: ['ops-weekly'] })
  }

  const sync = useMutation({
    mutationFn: () => opsApi.sync(),
    onSuccess: () => {
      setBanner('Business Central refresh finished. Nothing was emailed.')
      refreshAll()
    },
    onError: (error) => setBanner(detailOf(error, 'Business Central refresh failed. Stored rows were left as they were.')),
  })

  const save = useMutation({
    mutationFn: async ({ kind, id, body }) => {
      if (kind === 'order') return opsApi.patchOrder(id, body)
      if (kind === 'line') return opsApi.patchLine(id, body)
      return opsApi.patchPo(id, body)
    },
    onSuccess: () => {
      setBanner('')
      refreshAll()
    },
    onError: (error) => setBanner(detailOf(error, 'Could not save that change.')),
  })

  const data = tracker.data
  const vendors = data?.vendors || []
  const choices = data?.choices || {}

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-gray-900 sm:text-2xl">Order tracker</h1>
          <p className="mt-1 max-w-3xl text-sm text-gray-600">
            One row per sales order. Business Central fills the order, the purchase order, and the acknowledgement. Sourcing, operators, window kits, emergency builds, and shipping live here.
          </p>
        </div>
        <button
          type="button"
          onClick={() => sync.mutate()}
          disabled={sync.isPending}
          className="min-h-11 rounded-lg bg-odc-900 px-4 text-sm font-medium text-white disabled:opacity-60"
        >
          {sync.isPending ? 'Refreshing…' : 'Refresh from Business Central'}
        </button>
      </div>

      {banner && <p className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-950">{banner}</p>}
      {data?.mail && data.mail.available === false && (
        <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">{data.mail.reason}</p>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Open orders" value={data?.counts?.orders ?? '—'} />
        <Stat label="Late" value={data?.counts?.at_risk ?? '—'} tone="text-red-700" />
        <Stat label="To-do" value={data?.counts?.open_actions ?? '—'} />
        <Stat label="Waiting for approval" value={data?.counts?.pending_approvals ?? '—'} tone="text-amber-800" />
      </div>

      <div className="flex flex-wrap gap-2">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setParams(id === 'tracker' ? {} : { tab: id })}
            className={`rounded-full px-3 py-1.5 text-sm font-medium ${tab === id ? 'bg-odc-900 text-white' : 'bg-white text-gray-700 ring-1 ring-gray-200'}`}
          >
            {label}
          </button>
        ))}
        {data?.synced_at && <span className="self-center text-xs text-gray-500">Last refresh {new Date(data.synced_at).toLocaleString()}</span>}
      </div>

      {tracker.isLoading && <p className="text-sm text-gray-500">Loading orders…</p>}
      {tracker.isError && <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-800">{detailOf(tracker.error, 'The tracker could not be loaded.')}</p>}

      {tab === 'tracker' && data && (
        <OrderTable
          data={data}
          filters={filters}
          setFilters={setFilters}
          choices={choices}
          vendors={vendors}
          expanded={expanded}
          setExpanded={setExpanded}
          onSave={(kind, id, body) => save.mutate({ kind, id, body })}
        />
      )}
      {tab === 'pos' && data && <PoTable rows={data.purchase_orders || []} onSave={(id, body) => save.mutate({ kind: 'po', id, body })} />}
      {tab === 'todo' && <TodoList query={actions} onChanged={refreshAll} />}
      {tab === 'approvals' && <ApprovalQueue query={messages} onChanged={refreshAll} />}
      {tab === 'week' && <WeekPanel query={weekly} />}
    </div>
  )
}

function Stat({ label, value, tone = 'text-gray-900' }) {
  return (
    <div className="rounded-2xl bg-white px-4 py-3 ring-1 ring-gray-200">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}

function OrderTable({ data, filters, setFilters, choices, vendors, expanded, setExpanded, onSave }) {
  const vendorOptions = vendors.map((vendor) => ({ value: vendor.code, label: vendor.label }))
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <input
          aria-label="Search orders"
          value={filters.q}
          onChange={(event) => setFilters({ ...filters, q: event.target.value })}
          placeholder="Search SO, customer, tag, PO"
          className="min-h-10 flex-1 rounded-lg border border-gray-300 px-3 text-sm sm:max-w-xs"
        />
        <input
          aria-label="Filter by customer"
          value={filters.customer}
          onChange={(event) => setFilters({ ...filters, customer: event.target.value })}
          placeholder="Customer"
          className="min-h-10 rounded-lg border border-gray-300 px-3 text-sm"
        />
        <Select
          label="Filter by status"
          value={filters.status}
          options={[{ value: '', label: 'Any status' }, ...(choices.order_status || []).map((item) => ({ value: item, label: item }))]}
          onChange={(status) => setFilters({ ...filters, status })}
        />
        <Select
          label="Filter by supplier"
          value={filters.supplier}
          options={[{ value: '', label: 'Any supplier' }, ...vendorOptions]}
          onChange={(supplier) => setFilters({ ...filters, supplier })}
        />
        <Select
          label="Filter by PO status"
          value={filters.po_status}
          options={[{ value: '', label: 'Any PO status' }, ...((choices.lifecycle || []).map((item) => ({ value: item.value, label: item.label })))]}
          onChange={(po_status) => setFilters({ ...filters, po_status })}
        />
        <label className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-white px-3 text-sm text-gray-700 ring-1 ring-gray-200">
          <input
            type="checkbox"
            checked={filters.at_risk}
            onChange={(event) => setFilters({ ...filters, at_risk: event.target.checked })}
          />
          Late only
        </label>
      </div>
      <div className="overflow-x-auto rounded-2xl bg-white ring-1 ring-gray-200">
        <table className="min-w-[1100px] w-full text-left text-sm">
          <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
            <tr>
              {['SO', 'Customer', 'Tag', 'Order', 'PO date', 'Fulfillment', 'Purchase orders', 'Status', 'Expected', 'Operators', 'Window kits', 'Emergency', 'Shipping'].map((heading) => (
                <th key={heading} className={`whitespace-nowrap px-3 py-2 font-medium ${heading === 'SO' ? 'sticky left-0 z-10 bg-gray-50' : ''}`}>{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data.orders || []).length === 0 && (
              <tr><td colSpan={13} className="px-3 py-8 text-center text-gray-500">No orders match. Refresh from Business Central to pull open sales orders.</td></tr>
            )}
            {(data.orders || []).map((order) => (
              <OrderBlock
                key={order.so_number}
                order={order}
                choices={choices}
                vendorOptions={vendorOptions}
                open={expanded === order.so_number}
                onToggle={() => setExpanded(expanded === order.so_number ? null : order.so_number)}
                onSave={onSave}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function OrderBlock({ order, choices, vendorOptions, open, onToggle, onSave }) {
  const audit = useQuery({
    queryKey: ['ops-audit', order.so_number],
    queryFn: async () => (await opsApi.audit(order.so_number)).data,
    enabled: open,
  })
  return (
    <>
      <tr className={order.at_risk ? 'bg-red-50' : 'border-t border-gray-100'}>
        <td className={`sticky left-0 z-10 px-3 py-2 font-medium ${order.at_risk ? 'bg-red-50' : 'bg-white'}`}>
          <button type="button" onClick={onToggle} className="text-left text-odc-800">
            {open ? '▾' : '▸'} {order.so_number}
          </button>
          {order.at_risk && <div className="mt-1"><Pill tone="red">{order.days_late}d late</Pill></div>}
        </td>
        <td className="px-3 py-2">
          <div>{order.customer_name}</div>
          <div className="text-xs text-gray-500">{order.customer_number}</div>
        </td>
        <td className="px-3 py-2">{order.external_document_number || '—'}</td>
        <td className="px-3 py-2 whitespace-nowrap">{order.order_date || '—'}</td>
        <td className="px-3 py-2 whitespace-nowrap">{order.po_date || '—'}</td>
        <td className="px-3 py-2">
          <Select label={`Fulfillment for ${order.so_number}`} value={order.fulfillment} options={choices.fulfillment || []} onChange={(fulfillment) => onSave('order', order.so_number, { fulfillment })} />
        </td>
        <td className="px-3 py-2 align-top">
          <PoStack pos={order.purchase_orders || []} />
        </td>
        <td className="px-3 py-2">
          <Select label={`Status for ${order.so_number}`} value={order.order_status} options={choices.order_status || []} onChange={(order_status) => onSave('order', order.so_number, { order_status })} />
        </td>
        <td className="px-3 py-2">
          <input
            aria-label={`Expected receipt for ${order.so_number}`}
            type="date"
            defaultValue={order.expected_receipt || ''}
            key={`${order.so_number}-${order.expected_receipt}`}
            onChange={(event) => onSave('order', order.so_number, { expected_receipt: event.target.value || null })}
            className="rounded-md border border-gray-300 px-1.5 py-1 text-xs"
          />
          {order.supplier_expected && order.supplier_expected !== order.expected_receipt && (
            <button type="button" className="mt-1 block text-xs text-odc-800" onClick={() => onSave('order', order.so_number, { use_supplier_date: true })}>
              Use supplier date {order.supplier_expected}
            </button>
          )}
        </td>
        <td className="px-3 py-2"><Select label={`Operators for ${order.so_number}`} value={order.operators} options={choices.operators || []} onChange={(operators) => onSave('order', order.so_number, { operators })} /></td>
        <td className="px-3 py-2"><Select label={`Window kits for ${order.so_number}`} value={order.window_kits} options={choices.window_kits || []} onChange={(window_kits) => onSave('order', order.so_number, { window_kits })} /></td>
        <td className="px-3 py-2"><Select label={`Emergency build for ${order.so_number}`} value={order.emergency_build} options={choices.emergency_build || []} onChange={(emergency_build) => onSave('order', order.so_number, { emergency_build })} /></td>
        <td className="px-3 py-2">
          <Select label={`Shipping for ${order.so_number}`} value={order.shipping_status} options={choices.shipping_status || []} onChange={(shipping_status) => onSave('order', order.so_number, { shipping_status })} />
        </td>
      </tr>
      {open && (
        <tr className="border-t border-gray-100 bg-gray-50">
          <td colSpan={13} className="px-3 py-3">
            <div className="mb-3 flex flex-wrap gap-3 text-sm">
              <label className="text-xs text-gray-500">
                Customer email
                <input
                  aria-label={`Customer email for ${order.so_number}`}
                  defaultValue={order.customer_email || ''}
                  key={`${order.so_number}-email-${order.customer_email}`}
                  onBlur={(event) => onSave('order', order.so_number, { customer_email: event.target.value })}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1 text-sm"
                />
              </label>
              <label className="min-w-[16rem] flex-1 text-xs text-gray-500">
                Notes
                <input
                  aria-label={`Notes for ${order.so_number}`}
                  defaultValue={order.notes || ''}
                  key={`${order.so_number}-notes-${order.notes}`}
                  onBlur={(event) => onSave('order', order.so_number, { notes: event.target.value })}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1 text-sm"
                />
              </label>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase text-gray-500">
                  <tr>
                    {['Item', 'Qty', 'Sourcing', 'Linked PO', 'Ack', 'Expected', 'Notes'].map((heading) => (
                      <th key={heading} className="px-2 py-1 font-medium">{heading}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {order.lines.map((line) => (
                    <tr key={line.id} className="border-t border-gray-200">
                      <td className="px-2 py-2">
                        <div className="font-medium">{line.item_no}</div>
                        <div className="text-xs text-gray-500">{line.description}</div>
                        {line.missing_flag && (
                          <p className="mt-1 text-xs text-red-700">
                            Missing. On hand {line.stock_qty ?? 'unknown'} at {line.stock_location || 'Redcliff'} ({line.stock_source || 'not checked'}).
                          </p>
                        )}
                      </td>
                      <td className="px-2 py-2 tabular-nums">{line.quantity}</td>
                      <td className="px-2 py-2">
                        <Select
                          label={`Sourcing for ${line.item_no}`}
                          value={line.source_code}
                          options={vendorOptions}
                          onChange={(source_code) => {
                            const vendor = vendorOptions.find((option) => option.value === source_code)
                            onSave('line', line.id, { source_code, source_label: vendor?.label || source_code })
                          }}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <input
                          aria-label={`Linked PO for ${line.item_no}`}
                          defaultValue={line.linked_po_number || ''}
                          key={`${line.id}-${line.linked_po_number}`}
                          onBlur={(event) => onSave('line', line.id, { linked_po_number: event.target.value })}
                          className="w-28 rounded-md border border-gray-300 px-2 py-1 text-xs"
                        />
                      </td>
                      <td className="px-2 py-2">
                        <Select label={`Ack for ${line.item_no}`} value={line.ack_status} options={choicesForAck(line)} onChange={(ack_status) => onSave('line', line.id, { ack_status })} />
                      </td>
                      <td className="px-2 py-2">
                        <input
                          aria-label={`Expected date for ${line.item_no}`}
                          type="date"
                          defaultValue={line.expected_date || ''}
                          key={`${line.id}-date-${line.expected_date}`}
                          onChange={(event) => onSave('line', line.id, { expected_date: event.target.value || null })}
                          className="rounded-md border border-gray-300 px-1.5 py-1 text-xs"
                        />
                      </td>
                      <td className="px-2 py-2">
                        <input
                          aria-label={`Notes for ${line.item_no}`}
                          defaultValue={line.notes || ''}
                          key={`${line.id}-notes-${line.notes}`}
                          onBlur={(event) => onSave('line', line.id, { notes: event.target.value })}
                          className="w-40 rounded-md border border-gray-300 px-2 py-1 text-xs"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(order.communications || []).length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Sent updates</p>
                <ul className="mt-1 space-y-1 text-sm text-gray-700">
                  {order.communications.map((message) => (
                    <li key={message.id}>{message.sent_at?.slice(0, 10)} · {message.subject} · {message.to_email}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="mt-3">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Communications</p>
              <Communications rows={order.communications || []} />
            </div>
            <div className="mt-3">
              <ActivityLog soNumber={order.so_number} title={`Notes for ${order.so_number}`} />
            </div>
            <div className="mt-3">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Changes</p>
              <ul className="mt-1 space-y-1 text-xs text-gray-600">
                {(audit.data?.audit || []).slice(0, 8).map((row) => (
                  <li key={row.id}>{row.created_at?.replace('T', ' ').slice(0, 16)} · {row.actor_email || row.source} set {row.field} to {row.new_value || 'blank'}</li>
                ))}
                {audit.data && audit.data.audit.length === 0 && <li>No edits yet.</li>}
              </ul>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function choicesForAck(line) {
  return ['none', 'pending', 'acknowledged', 'revised', 'cancelled', 'not_required'].map((value) => ({
    value,
    label: line.ack_status === value ? value : value,
  }))
}

function PoTable({ rows, onSave }) {
  const [logPo, setLogPo] = useState(null)
  return (
    <div className="space-y-3">
    <div className="overflow-x-auto rounded-2xl bg-white ring-1 ring-gray-200">
      <table className="min-w-[900px] w-full text-left text-sm">
        <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
          <tr>
            {['PO', 'Vendor', 'Status', 'PO date', 'Expected', 'Sales orders', 'Ack', 'Vendor order', 'Email', 'Notes'].map((heading) => (
              <th key={heading} className="px-3 py-2 font-medium">{heading}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={10} className="px-3 py-8 text-center text-gray-500">No open purchase orders on the tracker yet.</td></tr>}
          {rows.map((po) => (
            <tr key={po.po_number} className="border-t border-gray-100">
              <td className="px-3 py-2 font-medium">
                {po.po_number}
                <div className="mt-1"><Pill tone={po.lifecycle === 'waiting_ack' ? 'amber' : po.lifecycle === 'issue' ? 'red' : 'gray'}>{po.lifecycle_label || po.lifecycle}</Pill></div>
              </td>
              <td className="px-3 py-2">{po.vendor_name || po.vendor_number}</td>
              <td className="px-3 py-2">{po.status}</td>
              <td className="px-3 py-2">{po.order_date || '—'}</td>
              <td className="px-3 py-2">{po.expected_date || '—'}</td>
              <td className="px-3 py-2">{(po.so_numbers || []).join(', ') || '—'}</td>
              <td className="px-3 py-2"><Pill tone={po.ack_status === 'acknowledged' || po.ack_status === 'revised' ? 'green' : 'amber'}>{po.ack_status}</Pill></td>
              <td className="px-3 py-2">{po.vendor_order_no || '—'}</td>
              <td className="px-3 py-2">
                <input
                  aria-label={`Vendor email for ${po.po_number}`}
                  defaultValue={po.vendor_email || ''}
                  key={`${po.po_number}-${po.vendor_email}`}
                  onBlur={(event) => onSave(po.po_number, { vendor_email: event.target.value })}
                  className="w-44 rounded-md border border-gray-300 px-2 py-1 text-xs"
                />
              </td>
              <td className="px-3 py-2">
                <input
                  aria-label={`Notes for ${po.po_number}`}
                  defaultValue={po.notes || ''}
                  key={`${po.po_number}-notes-${po.notes}`}
                  onBlur={(event) => onSave(po.po_number, { notes: event.target.value })}
                  className="w-40 rounded-md border border-gray-300 px-2 py-1 text-xs"
                />
                <button type="button" onClick={() => setLogPo(logPo === po.po_number ? null : po.po_number)} className="mt-1 block text-xs text-odc-800">
                  {logPo === po.po_number ? 'Hide log' : 'Activity log'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    {logPo && <ActivityLog poNumber={logPo} title={`Notes for ${logPo}`} />}
    </div>
  )
}

function TodoList({ query, onChanged }) {
  const [form, setForm] = useState({ title: '', so_number: '', due_on: '', detail: '' })
  const [error, setError] = useState('')
  const create = useMutation({
    mutationFn: (body) => opsApi.followUp(body),
    onSuccess: () => {
      setForm({ title: '', so_number: '', due_on: '', detail: '' })
      setError('')
      onChanged()
      query.refetch()
    },
    onError: (err) => setError(detailOf(err, 'Could not add that follow-up.')),
  })
  const done = useMutation({
    mutationFn: (id) => opsApi.done(id),
    onSuccess: () => {
      onChanged()
      query.refetch()
    },
    onError: (err) => setError(detailOf(err, 'That item closes on its own.')),
  })
  const rows = query.data?.actions || []
  return (
    <div className="space-y-4">
      {query.data?.mail && query.data.mail.available === false && (
        <p className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-950">{query.data.mail.reason}</p>
      )}
      <form
        className="grid gap-2 rounded-2xl bg-white p-4 ring-1 ring-gray-200 sm:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate(form)
        }}
      >
        <input required aria-label="Follow-up title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="Follow up about…" className="min-h-10 rounded-lg border border-gray-300 px-3 text-sm sm:col-span-2" />
        <input aria-label="Follow-up sales order" value={form.so_number} onChange={(event) => setForm({ ...form, so_number: event.target.value })} placeholder="SO-10421" className="min-h-10 rounded-lg border border-gray-300 px-3 text-sm" />
        <input aria-label="Follow-up date" type="date" value={form.due_on} onChange={(event) => setForm({ ...form, due_on: event.target.value })} className="min-h-10 rounded-lg border border-gray-300 px-3 text-sm" />
        <button type="submit" className="min-h-10 rounded-lg bg-odc-900 px-3 text-sm font-medium text-white sm:col-span-4 sm:justify-self-start">Add follow-up</button>
      </form>
      {error && <p className="text-sm text-red-700">{error}</p>}
      <ul className="divide-y divide-gray-100 rounded-2xl bg-white ring-1 ring-gray-200">
        {rows.length === 0 && <li className="px-4 py-6 text-sm text-gray-500">Nothing open. Missing links and replies show up here after a refresh.</li>}
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
            <div>
              <p className="text-sm font-medium text-gray-900">{row.title}</p>
              <p className="text-xs text-gray-500">{row.detail}</p>
              <p className="mt-1 text-xs text-gray-400">{row.kind.replaceAll('_', ' ')}{row.due_at ? ` · due ${row.due_at.slice(0, 10)}` : ''}</p>
            </div>
            <div className="flex items-center gap-2">
              {row.overdue && <Pill tone="red">Overdue</Pill>}
              {(row.kind === 'follow_up' || row.kind === 'needs_reply') && (
                <button type="button" onClick={() => done.mutate(row.id)} className="rounded-lg px-3 py-1.5 text-sm font-medium text-odc-800 ring-1 ring-gray-200">
                  {row.kind === 'follow_up' ? 'Done' : 'Dismiss'}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ApprovalQueue({ query, onChanged }) {
  const [drafts, setDrafts] = useState({})
  const [error, setError] = useState('')
  const rows = query.data?.messages || []

  function draftFor(message) {
    return drafts[message.id] || { to_email: message.to_email || '', subject: message.subject, body_text: message.body_text }
  }

  const approve = useMutation({
    mutationFn: async (message) => {
      const draft = draftFor(message)
      await opsApi.editMessage(message.id, draft)
      return opsApi.approve(message.id)
    },
    onSuccess: () => {
      setError('')
      onChanged()
      query.refetch()
    },
    onError: (err) => setError(detailOf(err, 'The email was not sent.')),
  })
  const reject = useMutation({
    mutationFn: (id) => opsApi.reject(id),
    onSuccess: () => {
      setError('')
      onChanged()
      query.refetch()
    },
    onError: (err) => setError(detailOf(err, 'Could not reject that draft.')),
  })

  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-600">These emails are drafts. Nothing goes out until you approve it.</p>
      {error && <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}
      {rows.length === 0 && <p className="rounded-2xl bg-white px-4 py-6 text-sm text-gray-500 ring-1 ring-gray-200">No emails waiting. A supplier reminder or a customer date change will land here first.</p>}
      {rows.map((message) => {
        const draft = draftFor(message)
        return (
          <article key={message.id} className="space-y-3 rounded-2xl bg-white p-4 ring-1 ring-gray-200">
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone={message.kind === 'customer_update' ? 'blue' : 'amber'}>{message.kind === 'customer_update' ? 'Customer update' : 'Supplier reminder'}</Pill>
              <span className="text-xs text-gray-500">{message.so_number} {message.po_number}</span>
            </div>
            <label className="block text-xs text-gray-500">
              To
              <input
                aria-label={`Recipient for ${message.subject}`}
                value={draft.to_email}
                onChange={(event) => setDrafts({ ...drafts, [message.id]: { ...draft, to_email: event.target.value } })}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs text-gray-500">
              Subject
              <input
                aria-label={`Subject for message ${message.id}`}
                value={draft.subject}
                onChange={(event) => setDrafts({ ...drafts, [message.id]: { ...draft, subject: event.target.value } })}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs text-gray-500">
              Message
              <textarea
                aria-label={`Body for message ${message.id}`}
                value={draft.body_text}
                onChange={(event) => setDrafts({ ...drafts, [message.id]: { ...draft, body_text: event.target.value } })}
                rows={6}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={approve.isPending}
                onClick={() => {
                  if (window.confirm(`Send this email to ${draft.to_email || 'the recipient'}?`)) approve.mutate(message)
                }}
                className="min-h-10 rounded-lg bg-odc-900 px-4 text-sm font-medium text-white disabled:opacity-60"
              >
                Approve and send
              </button>
              <button type="button" onClick={() => reject.mutate(message.id)} className="min-h-10 rounded-lg px-4 text-sm font-medium text-gray-700 ring-1 ring-gray-300">
                Reject
              </button>
            </div>
          </article>
        )
      })}
    </div>
  )
}

function WeekPanel({ query }) {
  const report = query.data
  if (query.isLoading) return <p className="text-sm text-gray-500">Loading the week…</p>
  if (!report) return <p className="text-sm text-gray-500">No summary yet.</p>
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">Week of {report.week_start} to {report.week_ending}. {report.definitions?.nothing_sends_automatically}</p>
      <div className="grid gap-3 lg:grid-cols-2">
        <NumberTable title="Lead time by supplier" columns={['Supplier', 'Orders', 'Avg days']} rows={(report.lead_time_days_by_supplier || []).map((row) => [row.supplier, row.samples, row.avg_lead_days])} note={report.definitions?.lead_time_days} />
        <NumberTable title="Acknowledgement turnaround" columns={['Supplier', 'Acks', 'Avg days']} rows={(report.ack_turnaround_days_by_supplier || []).map((row) => [row.supplier, row.acks, row.avg_days])} note={report.definitions?.ack_turnaround_days} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-2xl bg-white p-4 ring-1 ring-gray-200">
          <h3 className="text-sm font-semibold text-gray-900">Customer updates</h3>
          <p className="mt-2 text-sm text-gray-700">Drafted {report.customer_updates.drafted} · Sent {report.customer_updates.sent} · Rejected {report.customer_updates.rejected} · Waiting {report.customer_updates.pending_now}</p>
        </div>
        <div className="rounded-2xl bg-white p-4 ring-1 ring-gray-200">
          <h3 className="text-sm font-semibold text-gray-900">Supplier reminders</h3>
          <p className="mt-2 text-sm text-gray-700">Drafted {report.supplier_reminders.drafted} · Sent {report.supplier_reminders.sent} · Waiting {report.supplier_reminders.pending_now}</p>
        </div>
      </div>
      <div className="rounded-2xl bg-white ring-1 ring-gray-200">
        <h3 className="px-4 pt-4 text-sm font-semibold text-gray-900">Late orders</h3>
        <ul className="divide-y divide-gray-100">
          {(report.late_orders || []).length === 0 && <li className="px-4 py-4 text-sm text-gray-500">No late orders.</li>}
          {(report.late_orders || []).map((row) => (
            <li key={row.so_number} className="flex justify-between px-4 py-3 text-sm">
              <span>{row.so_number} · {row.customer}</span>
              <span className="text-red-700">{row.days_late}d past {row.expected_receipt}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function NumberTable({ title, columns, rows, note }) {
  return (
    <div className="rounded-2xl bg-white ring-1 ring-gray-200">
      <h3 className="px-4 pt-4 text-sm font-semibold text-gray-900">{title}</h3>
      <p className="px-4 pt-1 text-xs text-gray-500">{note}</p>
      <table className="mt-2 w-full text-left text-sm">
        <thead className="text-xs uppercase text-gray-500">
          <tr>{columns.map((column) => <th key={column} className="px-4 py-2 font-medium">{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={columns.length} className="px-4 py-3 text-gray-500">No samples yet.</td></tr>}
          {rows.map((row) => (
            <tr key={row[0]} className="border-t border-gray-100">
              {row.map((cell, index) => <td key={index} className="px-4 py-2">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default ProductionTracker
