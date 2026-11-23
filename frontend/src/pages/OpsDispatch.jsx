import { useCallback, useEffect, useState } from 'react'
import { opsDispatchApi } from '../api/client'

function Pill({ children, tone }) {
  const tones = {
    red: 'bg-red-100 text-red-900',
    amber: 'bg-amber-100 text-amber-900',
    green: 'bg-green-100 text-green-900',
    blue: 'bg-blue-100 text-blue-900',
    gray: 'bg-gray-100 text-gray-700',
  }
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${tones[tone] || tones.gray}`}>
      {children}
    </span>
  )
}

export function OpsDispatchView({ data, notice, onApprove, onReject, onOpenPdf, busyId }) {
  const late = data?.late || { late: [], late_count: 0, open_count: 0 }
  const flags = data?.flags || []
  const updates = data?.customer_updates || []
  const slips = data?.packing_slips || []
  const switches = data?.flags_enabled || {}

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Planning flags</h1>
        <p className="mt-1 text-sm text-gray-600">
          Late sales orders, purchase orders waiting on a supplier date, customer updates
          waiting for approval, and packing slips. Nothing on this page sends until you approve it.
        </p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-600">
          <Pill tone={switches.supplier_confirm_intake ? 'green' : 'gray'}>
            Confirmation poll {switches.supplier_confirm_intake ? 'on' : 'off'}
          </Pill>
          <Pill tone={switches.supplier_confirm_bc_write ? 'amber' : 'gray'}>
            BC expected-date write {switches.supplier_confirm_bc_write ? 'on' : 'off'}
          </Pill>
          <Pill tone={switches.packing_slip_enabled ? 'green' : 'gray'}>
            Packing slip job {switches.packing_slip_enabled ? 'on' : 'off'}
          </Pill>
          <Pill tone={switches.packing_slip_auto_send ? 'amber' : 'gray'}>
            Packing slip auto-send {switches.packing_slip_auto_send ? 'on' : 'off'}
          </Pill>
        </div>
        {notice && <p className="mt-3 text-sm text-gray-800">{notice}</p>}
        {data?.bc_error && (
          <p className="mt-3 text-sm text-amber-800">Business Central was not reachable. Saved rows are still shown.</p>
        )}
      </div>

      <section>
        <h2 className="text-lg font-semibold text-gray-900">
          Late sales orders
          <span className="ml-2 text-sm font-normal text-gray-500">
            {late.late_count || 0} of {late.open_count || 0} not fully shipped
          </span>
        </h2>
        <LateTable rows={late.late || []} />
      </section>

      <section>
        <h2 className="text-lg font-semibold text-gray-900">Supplier confirmation flags</h2>
        <p className="mt-1 text-sm text-gray-600">
          Open purchase orders sent at least 3 business days ago with no confirmation, or no real expected receipt date.
          A date shared across the open book counts as no date.
        </p>
        <FlagTable rows={flags} />
      </section>

      <section>
        <h2 className="text-lg font-semibold text-gray-900">Customer updates waiting for approval</h2>
        <p className="mt-1 text-sm text-gray-600">
          These drafts are not sent. Approve them from the Order Tracker after you add the recipient.
        </p>
        <div className="mt-3 space-y-3">
          {updates.length === 0 && <p className="text-sm text-gray-500">No customer update is waiting.</p>}
          {updates.map((row) => (
            <article key={row.id} className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-gray-900">{row.so_number}</span>
                <span className="text-gray-700">{row.customer_name}</span>
                <Pill tone="blue">Draft</Pill>
                {row.new_date && <span className="text-sm text-gray-600">Expected {row.new_date}</span>}
              </div>
              <p className="mt-1 text-sm text-gray-600">{row.reason}</p>
              <pre className="mt-3 whitespace-pre-wrap rounded bg-gray-50 p-3 text-sm text-gray-800">{row.body_text}</pre>
            </article>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-gray-900">Packing slips</h2>
        <p className="mt-1 text-sm text-gray-600">
          Generated when a sales shipment is posted. Print the PDF into the box. Email stays queued until you approve it.
        </p>
        <div className="mt-3 overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-3 py-2">Shipment</th>
                <th className="px-3 py-2">SO</th>
                <th className="px-3 py-2">Customer</th>
                <th className="px-3 py-2">Customer PO</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {slips.length === 0 && (
                <tr><td className="px-3 py-3 text-gray-500" colSpan={6}>No packing slips yet.</td></tr>
              )}
              {slips.map((slip) => (
                <tr key={slip.id} className="border-t border-gray-100">
                  <td className="px-3 py-2 font-medium">{slip.shipment_number}</td>
                  <td className="px-3 py-2">{slip.so_number}</td>
                  <td className="px-3 py-2">{slip.customer_name}</td>
                  <td className="px-3 py-2">{slip.customer_po}</td>
                  <td className="px-3 py-2">
                    <Pill tone={slip.status === 'sent' ? 'green' : slip.status === 'rejected' ? 'gray' : 'amber'}>
                      {slip.status}
                    </Pill>
                  </td>
                  <td className="px-3 py-2 text-right space-x-2">
                    <button
                      type="button"
                      className="text-blue-700 hover:underline"
                      onClick={() => onOpenPdf(slip)}
                    >
                      PDF
                    </button>
                    {slip.status === 'draft' && (
                      <>
                        <button
                          type="button"
                          className="text-blue-700 hover:underline disabled:opacity-50"
                          disabled={busyId === slip.id}
                          onClick={() => onApprove(slip)}
                        >
                          Approve and email
                        </button>
                        <button
                          type="button"
                          className="text-gray-600 hover:underline disabled:opacity-50"
                          disabled={busyId === slip.id}
                          onClick={() => onReject(slip)}
                        >
                          Reject
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function LateTable({ rows }) {
  if (!rows.length) {
    return <p className="mt-2 text-sm text-gray-500">No open sales order is late.</p>
  }
  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-gray-200 bg-white">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50 text-left text-gray-600">
          <tr>
            <th className="px-3 py-2">SO</th>
            <th className="px-3 py-2">Customer</th>
            <th className="px-3 py-2">Requested</th>
            <th className="px-3 py-2">Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.so_number} className="border-t border-gray-100">
              <td className="px-3 py-2 font-medium">{row.so_number}</td>
              <td className="px-3 py-2">{row.customer}</td>
              <td className="px-3 py-2">{row.requested_date}</td>
              <td className="px-3 py-2">{row.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FlagTable({ rows }) {
  if (!rows.length) {
    return <p className="mt-2 text-sm text-gray-500">No purchase order is past the confirmation window.</p>
  }
  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-gray-200 bg-white">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50 text-left text-gray-600">
          <tr>
            <th className="px-3 py-2">PO</th>
            <th className="px-3 py-2">Vendor</th>
            <th className="px-3 py-2">Sent</th>
            <th className="px-3 py-2">Why</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.po_number} className="border-t border-gray-100">
              <td className="px-3 py-2 font-medium">{row.po_number}</td>
              <td className="px-3 py-2">{row.vendor}</td>
              <td className="px-3 py-2">{row.sent_on}</td>
              <td className="px-3 py-2">{row.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function OpsDispatch() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busyId, setBusyId] = useState(null)

  const load = useCallback(() => {
    opsDispatchApi.summary()
      .then((res) => {
        setData(res.data)
        setError('')
      })
      .catch((err) => {
        setError(err?.response?.data?.detail || 'Could not load planning flags.')
      })
  }, [])

  useEffect(() => { load() }, [load])

  async function onOpenPdf(slip) {
    try {
      const res = await opsDispatchApi.packingSlipPdf(slip.id)
      const url = URL.createObjectURL(res.data)
      window.open(url, '_blank', 'noopener')
    } catch (err) {
      setNotice(err?.response?.data?.detail || 'Could not open the packing slip.')
    }
  }

  async function onApprove(slip) {
    const email = slip.customer_email || window.prompt('Customer email for this packing slip')
    if (!email) return
    setBusyId(slip.id)
    setNotice('')
    try {
      await opsDispatchApi.approvePackingSlip(slip.id, email)
      setNotice(`Emailed packing slip ${slip.shipment_number}.`)
      load()
    } catch (err) {
      setNotice(err?.response?.data?.detail || 'The packing slip was not sent.')
    } finally {
      setBusyId(null)
    }
  }

  async function onReject(slip) {
    setBusyId(slip.id)
    try {
      await opsDispatchApi.rejectPackingSlip(slip.id)
      setNotice(`Rejected packing slip ${slip.shipment_number}. It was not emailed.`)
      load()
    } catch (err) {
      setNotice(err?.response?.data?.detail || 'Could not reject the packing slip.')
    } finally {
      setBusyId(null)
    }
  }

  if (error && !data) {
    return <p className="text-sm text-red-700">{error}</p>
  }
  if (!data) {
    return <p className="text-sm text-gray-500">Loading planning flags…</p>
  }
  return (
    <OpsDispatchView
      data={data}
      notice={notice}
      busyId={busyId}
      onApprove={onApprove}
      onReject={onReject}
      onOpenPdf={onOpenPdf}
    />
  )
}
