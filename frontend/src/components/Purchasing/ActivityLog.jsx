import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { opsApi } from '../../api/client'

function detailOf(error, fallback) {
  return error?.response?.data?.detail || fallback
}

const LABELS = {
  note: 'Note',
  po_recorded: 'PO recorded',
  po_sent: 'PO sent',
  ack_received: 'Acknowledgement',
  expected_date_changed: 'Expected date',
  reminder_drafted: 'Reminder drafted',
  reminder_sent: 'Reminder sent',
  reminder_rejected: 'Reminder rejected',
  sourcing_changed: 'Sourcing',
  follow_up: 'Follow-up',
  po_emailed: 'PO emailed',
  supplier_reply: 'Supplier reply',
  po_draft_saved: 'Draft saved',
}

export function ActivityLog({ soNumber = '', poNumber = '', title = 'Activity' }) {
  const queryClient = useQueryClient()
  const locked = Boolean(soNumber || poNumber)
  const [so, setSo] = useState(soNumber)
  const [po, setPo] = useState(poNumber)
  const [vendor, setVendor] = useState('')
  const [q, setQ] = useState('')
  const [body, setBody] = useState('')
  const [noteSo, setNoteSo] = useState(soNumber)
  const [notePo, setNotePo] = useState(poNumber)
  const [followUpOn, setFollowUpOn] = useState('')
  const [error, setError] = useState('')

  const activity = useQuery({
    queryKey: ['ops-activity', soNumber || so, poNumber || po, vendor, q],
    queryFn: async () => (await opsApi.activity({
      so_number: (soNumber || so) || undefined,
      po_number: (poNumber || po) || undefined,
      vendor: vendor || undefined,
      q: q || undefined,
    })).data,
  })

  const save = useMutation({
    mutationFn: (payload) => opsApi.addNote(payload),
    onSuccess: () => {
      setBody('')
      setFollowUpOn('')
      setError('')
      queryClient.invalidateQueries({ queryKey: ['ops-activity'] })
      queryClient.invalidateQueries({ queryKey: ['ops-purchasing-work'] })
      queryClient.invalidateQueries({ queryKey: ['ops-actions'] })
    },
    onError: (err) => setError(detailOf(err, 'The note was not saved.')),
  })

  const rows = activity.data?.activity || []
  return (
    <section className="rounded-lg border bg-white p-4">
      <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
      <p className="mt-1 text-xs text-gray-500">What happened on the order, who did it, and when. A follow-up date stays on the to-do list until it is marked done.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {!locked && (
          <>
            <input aria-label="Filter activity by sales order" value={so} onChange={(event) => setSo(event.target.value)} placeholder="SO-10421" className="min-h-10 rounded-lg border px-3 text-sm" />
            <input aria-label="Filter activity by purchase order" value={po} onChange={(event) => setPo(event.target.value)} placeholder="PO-001079" className="min-h-10 rounded-lg border px-3 text-sm" />
            <input aria-label="Filter activity by vendor" value={vendor} onChange={(event) => setVendor(event.target.value)} placeholder="Vendor" className="min-h-10 rounded-lg border px-3 text-sm" />
          </>
        )}
        <input aria-label="Search activity" value={q} onChange={(event) => setQ(event.target.value)} placeholder="Search notes" className="min-h-10 flex-1 rounded-lg border px-3 text-sm" />
      </div>
      <form
        className="mt-3 grid gap-2 sm:grid-cols-[1fr_10rem_auto]"
        onSubmit={(event) => {
          event.preventDefault()
          save.mutate({
            body,
            so_number: (soNumber || noteSo) || null,
            po_number: (poNumber || notePo) || null,
            follow_up_on: followUpOn || null,
          })
        }}
      >
        <textarea
          required
          aria-label="Activity note"
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={2}
          placeholder="Ian says the package is waiting for a waybill"
          className="rounded-lg border px-3 py-2 text-sm sm:col-span-3"
        />
        {!soNumber && (
          <input aria-label="Note sales order" value={noteSo} onChange={(event) => setNoteSo(event.target.value)} placeholder="Note on SO-10421" className="min-h-10 rounded-lg border px-3 text-sm" />
        )}
        {!poNumber && (
          <input aria-label="Note purchase order" value={notePo} onChange={(event) => setNotePo(event.target.value)} placeholder="Note on PO-001079" className="min-h-10 rounded-lg border px-3 text-sm" />
        )}
        <input aria-label="Follow-up date" type="date" value={followUpOn} onChange={(event) => setFollowUpOn(event.target.value)} className="min-h-10 rounded-lg border px-3 text-sm" />
        <button type="submit" disabled={save.isPending} className="min-h-10 rounded-lg bg-gray-900 px-3 text-sm font-medium text-white disabled:opacity-60">Add note</button>
      </form>
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
      <ol className="mt-4 space-y-3">
        {rows.length === 0 && <li className="text-sm text-gray-500">No notes yet.</li>}
        {rows.map((row) => (
          <li key={row.id} className="border-l-2 border-gray-200 pl-3">
            <p className="text-xs text-gray-500">
              {(row.created_at || '').replace('T', ' ').slice(0, 16)} · {LABELS[row.event_type] || row.event_type} · {row.actor_email || 'portal'}
              {row.so_number ? ` · ${row.so_number}` : ''}{row.po_number ? ` · ${row.po_number}` : ''}{row.vendor_name ? ` · ${row.vendor_name}` : ''}
            </p>
            <p className="text-sm text-gray-900">{row.body}</p>
            {row.follow_up_on && <p className="text-xs text-amber-800">Follow up {row.follow_up_on}</p>}
          </li>
        ))}
      </ol>
    </section>
  )
}

export function PurchasingWork() {
  const queryClient = useQueryClient()
  const [error, setError] = useState('')
  const work = useQuery({
    queryKey: ['ops-purchasing-work'],
    queryFn: async () => (await opsApi.purchasingWork()).data,
  })
  const done = useMutation({
    mutationFn: (id) => opsApi.done(id),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['ops-purchasing-work'] })
      queryClient.invalidateQueries({ queryKey: ['ops-actions'] })
    },
    onError: (err) => setError(detailOf(err, 'That item closes when the order is updated.')),
  })
  const approve = useMutation({
    mutationFn: (id) => opsApi.approve(id),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['ops-purchasing-work'] })
      queryClient.invalidateQueries({ queryKey: ['ops-messages'] })
      queryClient.invalidateQueries({ queryKey: ['ops-activity'] })
    },
    onError: (err) => setError(detailOf(err, 'The reminder was not sent.')),
  })
  const reject = useMutation({
    mutationFn: (id) => opsApi.reject(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ops-purchasing-work'] }),
    onError: (err) => setError(detailOf(err, 'Could not reject that reminder.')),
  })
  const actions = work.data?.actions || []
  const reminders = work.data?.reminders || []
  return (
    <section className="rounded-lg border bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Purchasing to-do</h2>
          <p className="text-xs text-gray-500">The same open purchasing items as the order tracker. Approving a reminder is the only way it is emailed.</p>
        </div>
        <span className="rounded-full bg-gray-900 px-3 py-1 text-xs font-medium text-white">{actions.length + reminders.length} open</span>
      </div>
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
      <ul className="mt-3 divide-y divide-gray-100">
        {actions.length === 0 && reminders.length === 0 && <li className="py-3 text-sm text-gray-500">Nothing purchasing-related is open.</li>}
        {reminders.map((row) => (
          <li key={`m-${row.id}`} className="flex flex-wrap items-start justify-between gap-3 py-3">
            <div>
              <p className="text-sm font-medium text-gray-900">{row.subject}</p>
              <p className="text-xs text-gray-500">To {row.to_email || 'no address yet'} · waiting for approval</p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  if (window.confirm(`Send this reminder to ${row.to_email}?`)) approve.mutate(row.id)
                }}
                className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white"
              >
                Approve and send
              </button>
              <button type="button" onClick={() => reject.mutate(row.id)} className="rounded-lg px-3 py-1.5 text-sm ring-1 ring-gray-300">Reject</button>
            </div>
          </li>
        ))}
        {actions.map((row) => (
          <li key={row.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
            <div>
              <p className="text-sm font-medium text-gray-900">{row.title}</p>
              <p className="text-xs text-gray-500">{row.detail}</p>
            </div>
            <div className="flex items-center gap-2">
              {row.overdue && <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">Overdue</span>}
              {row.kind === 'follow_up' && (
                <button type="button" onClick={() => done.mutate(row.id)} className="rounded-lg px-3 py-1.5 text-sm ring-1 ring-gray-300">Done</button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
