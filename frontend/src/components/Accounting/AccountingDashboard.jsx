import { useEffect, useMemo, useState } from 'react'
import { invoiceIntakeApi } from '../../api/client'

const TABS = [
  { id: 'attention', label: 'Needs attention' },
  { id: 'all', label: 'All AI activity' },
  { id: 'created', label: 'BC drafts' },
  { id: 'errors', label: 'Errors & duplicates' },
]

const STATUS_STYLES = {
  pending: 'bg-amber-100 text-amber-800',
  created: 'bg-green-100 text-green-800',
  error: 'bg-red-100 text-red-800',
  duplicate_skipped: 'bg-gray-100 text-gray-700',
}

function money(amount, currency) {
  if (amount == null || amount === '') return '—'
  const n = Number(amount)
  if (Number.isNaN(n)) return '—'
  try {
    return n.toLocaleString(undefined, {
      style: 'currency',
      currency: currency || 'CAD',
      minimumFractionDigits: 2,
    })
  } catch {
    return `$${n.toFixed(2)}`
  }
}

function when(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

function statusLabel(status) {
  return {
    pending: 'Needs review',
    created: 'BC Draft created',
    error: 'Error',
    duplicate_skipped: 'Duplicate skipped',
  }[status] || status
}

export default function AccountingDashboard() {
  const [tab, setTab] = useState('attention')
  const [search, setSearch] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null)
  const [message, setMessage] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [vendorNumber, setVendorNumber] = useState('')

  async function load() {
    setLoading(true)
    try {
      const params = {}
      if (search.trim()) params.q = search.trim()
      if (tab === 'created') params.status = 'created'
      const res = await invoiceIntakeApi.list(params)
      setData(res.data)
    } catch (e) {
      setMessage({ type: 'error', text: e.response?.data?.detail || e.message || 'Failed to load invoices' })
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [tab]) // eslint-disable-line react-hooks/exhaustive-deps

  async function openDetail(id) {
    setSelectedId(id)
    setDetail(null)
    setVendorNumber('')
    try {
      const res = await invoiceIntakeApi.get(id)
      setDetail(res.data)
    } catch (e) {
      setMessage({ type: 'error', text: e.response?.data?.detail || 'Failed to load invoice detail' })
    }
  }

  async function runNow() {
    setBusy('run')
    setMessage(null)
    try {
      const res = await invoiceIntakeApi.runNow()
      const r = res.data || {}
          if (typeof r.error === 'string') {
            setMessage({ type: 'error', text: `Mailbox check failed: ${r.error}` })
          } else {
            setMessage({
              type: 'success',
              text: `Mailbox check finished — processed ${r.processed || 0}, created ${r.created || 0}, pending ${r.pending || 0}, duplicates ${r.duplicate || 0}, errors ${r.error || 0}.`,
            })
          }
      await load()
    } catch (e) {
      setMessage({ type: 'error', text: e.response?.data?.detail || e.message })
    }
    setBusy(null)
  }

  async function markReviewed(id) {
    setBusy(`review-${id}`)
    try {
      await invoiceIntakeApi.markReviewed(id)
      await load()
      if (selectedId === id) await openDetail(id)
    } catch (e) {
      setMessage({ type: 'error', text: e.response?.data?.detail || e.message })
    }
    setBusy(null)
  }

  async function resolveVendor(id) {
    if (!vendorNumber.trim()) {
      setMessage({ type: 'error', text: 'Enter the Business Central vendor number.' })
      return
    }
    setBusy(`resolve-${id}`)
    try {
      const res = await invoiceIntakeApi.resolveVendor(id, vendorNumber.trim())
      const r = res.data || {}
      setMessage({
        type: r.success ? 'success' : 'warn',
        text: r.success
          ? `Vendor assigned. BC Draft ${r.bc_invoice_number || 'created'}.`
          : `Vendor assigned; outcome: ${r.outcome || r.error || 'pending'}`,
      })
      await load()
      await openDetail(id)
    } catch (e) {
      setMessage({ type: 'error', text: e.response?.data?.detail || e.message })
    }
    setBusy(null)
  }

  const invoices = data?.invoices || []
  const counts = data?.counts || {}
  const pipeline = data?.pipeline || {}

  const visible = useMemo(() => {
    if (tab === 'attention') {
      return invoices.filter((row) => (
        row.status === 'pending'
        || row.status === 'error'
        || (row.status === 'created' && !row.reviewed_at)
      ))
    }
    if (tab === 'errors') {
      return invoices.filter((row) => row.status === 'error' || row.status === 'duplicate_skipped')
    }
    return invoices
  }, [invoices, tab])

  const msgClass = {
    success: 'bg-green-50 text-green-800 border-green-200',
    error: 'bg-red-50 text-red-800 border-red-200',
    warn: 'bg-amber-50 text-amber-800 border-amber-200',
  }

  const extracted = detail?.extracted_json || {}
  const lineItems = extracted.line_items || []

  return (
    <div className="space-y-6 p-2">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Accounting</h1>
          <p className="mt-1 text-sm text-gray-500">
            Vendor invoices from the accounting mailbox — AI extraction, matching, and Business Central Draft entry.
            Drafts are never posted; you post them in BC after review.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => load()}
            className="px-3 py-2 text-sm border border-gray-300 rounded-md bg-white hover:bg-gray-50"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={runNow}
            disabled={busy === 'run'}
            className="px-3 py-2 text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
          >
            {busy === 'run' ? 'Checking mailbox…' : 'Check mailbox now'}
          </button>
        </div>
      </div>

      <div className={`rounded-lg border p-4 ${pipeline.enabled ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'}`}>
        <p className={`text-sm font-medium ${pipeline.enabled ? 'text-green-900' : 'text-amber-900'}`}>
          {pipeline.enabled
            ? `Watching ${pipeline.mailbox || 'the configured mailbox'} every ${pipeline.poll_interval_minutes || 30} minutes.`
            : `Mailbox watch is OFF. The pipeline is built, but INVOICE_INTAKE_ENABLED is false, so ${pipeline.mailbox || 'accounting@opendc.ca'} is not being polled.`}
        </p>
        <p className="mt-1 text-xs text-gray-600">
          Lookback {pipeline.lookback_hours || 24}h · Creates BC Drafts only (never posts)
          {pipeline.last_activity_at ? ` · Last AI activity ${when(pipeline.last_activity_at)}` : ' · No invoices processed yet'}
          {typeof pipeline.total_processed === 'number' ? ` · ${pipeline.total_processed} total` : ''}
        </p>
      </div>

      {message && (
        <div className={`rounded-md border p-3 text-sm ${msgClass[message.type] || msgClass.error}`}>
          {message.text}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: 'Needs review', value: counts.pending || 0, hint: 'Unmatched vendor / coding' },
          { label: 'BC Drafts', value: counts.created || 0, hint: 'Ready to post in BC' },
          { label: 'Unreviewed', value: counts.unreviewed || 0, hint: 'Not yet acknowledged' },
          { label: 'Errors', value: counts.error || 0, hint: 'Extraction or BC write failed' },
          { label: 'Duplicates skipped', value: counts.duplicate_skipped || 0, hint: 'Already in BC' },
        ].map((card) => (
          <div key={card.label} className="bg-white border border-gray-200 rounded-lg p-4">
            <p className="text-xs text-gray-500">{card.label}</p>
            <p className="mt-1 text-2xl font-semibold text-gray-900">{card.value}</p>
            <p className="mt-1 text-xs text-gray-400">{card.hint}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => { setTab(t.id); setSelectedId(null); setDetail(null) }}
            className={`px-3 py-1.5 text-sm rounded-md border ${
              tab === t.id
                ? 'bg-odc-50 border-odc-500 text-odc-800'
                : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
            }`}
          >
            {t.label}
          </button>
        ))}
        <form
          className="ml-auto flex gap-2"
          onSubmit={(e) => { e.preventDefault(); load() }}
        >
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search vendor, invoice #, sender…"
            className="w-64 max-w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm"
          />
          <button type="submit" className="px-3 py-1.5 text-sm border border-gray-300 rounded-md bg-white hover:bg-gray-50">
            Search
          </button>
        </form>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className={`${detail ? 'lg:col-span-3' : 'lg:col-span-5'} bg-white border border-gray-200 rounded-lg overflow-hidden`}>
          {loading ? (
            <p className="p-6 text-gray-500">Loading invoice activity…</p>
          ) : visible.length === 0 ? (
            <p className="p-6 text-gray-500">
              {pipeline.enabled
                ? 'No invoices in this view yet. New PDFs in the accounting mailbox will show up here after the next check.'
                : 'Nothing processed yet. Turn on mailbox watch (INVOICE_INTAKE_ENABLED) so the AI can start logging work here.'}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">When</th>
                    <th className="px-3 py-2 font-medium">Vendor / invoice</th>
                    <th className="px-3 py-2 font-medium">Amount</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">What the AI did</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((row) => (
                    <tr
                      key={row.id}
                      onClick={() => openDetail(row.id)}
                      className={`border-t border-gray-100 cursor-pointer hover:bg-odc-50 ${selectedId === row.id ? 'bg-odc-50' : ''}`}
                    >
                      <td className="px-3 py-3 whitespace-nowrap text-gray-500">{when(row.created_at)}</td>
                      <td className="px-3 py-3">
                        <div className="font-medium text-gray-900">{row.vendor_name_extracted || row.vendor_number || 'Unknown vendor'}</div>
                        <div className="text-xs text-gray-500">
                          {row.vendor_invoice_number || 'No invoice #'} · {row.attachment_filename}
                        </div>
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">{money(row.total_amount, row.currency_code)}</td>
                      <td className="px-3 py-3">
                        <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[row.status] || 'bg-gray-100 text-gray-700'}`}>
                          {statusLabel(row.status)}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-gray-700">{row.ai_action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {detail && (
          <div className="lg:col-span-2 bg-white border border-gray-200 rounded-lg p-4 space-y-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">
                  {detail.vendor_name_extracted || detail.vendor_number || 'Invoice'}
                </h2>
                <p className="text-sm text-gray-500">
                  {detail.vendor_invoice_number || 'No invoice #'} · {money(detail.total_amount, detail.currency_code)}
                </p>
              </div>
              <button type="button" onClick={() => { setDetail(null); setSelectedId(null) }} className="text-sm text-gray-500 hover:text-gray-800">
                Close
              </button>
            </div>

            <p className="text-sm text-gray-700">{detail.ai_action}</p>

            <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
              <div>
                <dt className="text-gray-500">From</dt>
                <dd>{detail.sender_email || '—'}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Received</dt>
                <dd>{when(detail.source_email_received_at)}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Invoice date</dt>
                <dd>{detail.invoice_date || '—'}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Due</dt>
                <dd>{detail.due_date || '—'}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Match</dt>
                <dd>
                  {detail.match_type === 'po' && `PO ${detail.matched_po_number}`}
                  {detail.match_type === 'gl' && `GL ${detail.gl_account_suggested} (${detail.gl_confidence || 'n/a'})`}
                  {(!detail.match_type || detail.match_type === 'unmatched') && 'Unmatched'}
                </dd>
              </div>
              <div>
                <dt className="text-gray-500">BC Draft</dt>
                <dd>{detail.bc_invoice_number || '—'}</dd>
              </div>
            </dl>

            {(detail.review_flags || []).length > 0 && (
              <div className="flex flex-wrap gap-1">
                {detail.review_flags.map((flag) => (
                  <span key={flag} className="text-xs bg-amber-50 text-amber-800 border border-amber-200 rounded px-2 py-0.5">
                    {flag.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            )}

            {detail.error_message && (
              <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">{detail.error_message}</p>
            )}

            {extracted.parsing_notes && (
              <p className="text-sm text-gray-600 italic">{extracted.parsing_notes}</p>
            )}

            {typeof extracted.overall_confidence === 'number' && (
              <p className="text-xs text-gray-500">
                Extraction confidence {(extracted.overall_confidence * 100).toFixed(0)}%
              </p>
            )}

            {lineItems.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-900 mb-2">Extracted lines</h3>
                <table className="w-full text-xs">
                  <thead className="text-gray-500">
                    <tr>
                      <th className="text-left py-1">Description</th>
                      <th className="text-right py-1">Qty</th>
                      <th className="text-right py-1">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lineItems.map((line, idx) => (
                      <tr key={idx} className="border-t border-gray-100">
                        <td className="py-1 pr-2">{line.description || '—'}</td>
                        <td className="py-1 text-right">{line.quantity ?? '—'}</td>
                        <td className="py-1 text-right">{money(line.line_total ?? line.unit_price, detail.currency_code)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {detail.status === 'pending' && (
              <div className="border-t border-gray-100 pt-3 space-y-2">
                <label className="block text-sm font-medium text-gray-700">Assign BC vendor number</label>
                <div className="flex gap-2">
                  <input
                    value={vendorNumber}
                    onChange={(e) => setVendorNumber(e.target.value)}
                    placeholder="e.g. ACE"
                    className="flex-1 border border-gray-300 rounded-md px-3 py-1.5 text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => resolveVendor(detail.id)}
                    disabled={busy === `resolve-${detail.id}`}
                    className="px-3 py-1.5 text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
                  >
                    Resolve
                  </button>
                </div>
                <p className="text-xs text-gray-500">Uses the already-extracted PDF data — no re-read of the email.</p>
              </div>
            )}

            <div className="border-t border-gray-100 pt-3 flex items-center justify-between">
              <p className="text-xs text-gray-500">
                {detail.reviewed_at
                  ? `Acknowledged ${when(detail.reviewed_at)}${detail.reviewed_by_name ? ` by ${detail.reviewed_by_name}` : ''}`
                  : 'Not yet acknowledged locally (BC posting is separate).'}
              </p>
              {!detail.reviewed_at && (
                <button
                  type="button"
                  onClick={() => markReviewed(detail.id)}
                  disabled={busy === `review-${detail.id}`}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-md bg-white hover:bg-gray-50 disabled:opacity-50"
                >
                  Mark reviewed
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
