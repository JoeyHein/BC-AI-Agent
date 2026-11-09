import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { opsApi } from '../../api/client'

const TYPE_LABELS = {
  their_sord_no_po: 'Their S-ORD, no PO of ours',
  our_open_po_missing: 'Our open PO missing from their list',
  received_still_open: 'Received by us, still open on theirs',
  ack_we_have_they_dont: 'We have an acknowledgement, they show none',
  ack_they_have_we_dont: 'They show an acknowledgement, we have none',
}

function detailOf(error, fallback) {
  return error?.response?.data?.detail || fallback
}

export default function UpwardorRecon() {
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [file, setFile] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [error, setError] = useState('')

  const list = useQuery({
    queryKey: ['upwardor-recon'],
    queryFn: async () => (await opsApi.upwardorRecon()).data,
  })
  const runs = list.data?.runs || []
  const activeId = selectedId || runs[0]?.id
  const detail = useQuery({
    queryKey: ['upwardor-recon', activeId],
    queryFn: async () => (await opsApi.upwardorReconRun(activeId)).data,
    enabled: Boolean(activeId),
  })

  const submit = useMutation({
    mutationFn: async () => {
      if (file) return opsApi.upwardorReconUpload(file)
      return opsApi.upwardorReconPaste(text)
    },
    onSuccess: (response) => {
      setError('')
      setText('')
      setFile(null)
      setSelectedId(response.data?.id || null)
      queryClient.invalidateQueries({ queryKey: ['upwardor-recon'] })
    },
    onError: (err) => setError(detailOf(err, 'That list could not be read.')),
  })

  const report = detail.data
  const exceptions = report?.exceptions || []
  const comparison = report?.comparison || {}
  const guide = list.data?.guide || report?.guide || []

  return (
    <section className="rounded-lg border bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Upwardor open orders</h2>
          <p className="mt-1 max-w-3xl text-xs text-gray-500">
            Bring in their weekly open-order list and compare it with Upwardor purchase orders already on the tracker.
            Refresh from Business Central first so the purchase orders are current. Nothing is emailed and nothing is written back to Business Central.
          </p>
        </div>
        {runs.length > 0 && (
          <label className="text-xs text-gray-500">
            Saved run
            <select
              aria-label="Saved reconciliation run"
              value={activeId || ''}
              onChange={(event) => setSelectedId(Number(event.target.value))}
              className="mt-1 block rounded-lg border px-2 py-1.5 text-sm text-gray-900"
            >
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {(run.created_at || '').slice(0, 16).replace('T', ' ')} · {run.row_count} rows
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <form
        className="mt-3 space-y-2"
        onSubmit={(event) => {
          event.preventDefault()
          submit.mutate()
        }}
      >
        <textarea
          aria-label="Paste Upwardor open orders"
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={4}
          placeholder={'Sales Order No.,Customer PO,Part No.,Ship Date\nS-ORD116299,PO-001066,PN10,2026-11-30'}
          className="w-full rounded-lg border px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap items-center gap-2">
          <input
            aria-label="Upload Upwardor open-order file"
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
            className="text-sm"
          />
          <button
            type="submit"
            disabled={submit.isPending || (!text.trim() && !file)}
            className="min-h-10 rounded-lg bg-gray-900 px-3 text-sm font-medium text-white disabled:opacity-60"
          >
            {submit.isPending ? 'Comparing…' : 'Compare with our POs'}
          </button>
        </div>
      </form>
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}

      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-gray-600">Column names this accepts</summary>
        <ul className="mt-2 space-y-1 text-xs text-gray-600">
          {guide.map((row) => (
            <li key={row.field}>
              <span className="font-medium text-gray-800">{row.uses}</span> Headers: {(row.accepted_headers || []).slice(0, 6).join(', ')}.
              A column is also recognized when the cells themselves look like an S-ORD or a PO number.
            </li>
          ))}
          {guide.length === 0 && <li>Loading the column guide…</li>}
        </ul>
      </details>

      {report && (
        <div className="mt-4 space-y-3">
          <p className="text-sm text-gray-700">
            {report.row_count} of their rows · {report.summary?.our_open_pos ?? '—'} open Upwardor POs on our side · {exceptions.length} exceptions.
            {comparison.previous_run_id
              ? ` Compared with run ${comparison.previous_run_id}: ${comparison.new_count} new, ${comparison.cleared_count} cleared.`
              : ' This is the first stored run.'}
          </p>
          {report.column_map && (
            <p className="text-xs text-gray-500">
              Columns used: {Object.entries(report.column_map).map(([field, header]) => `${field} = ${header}`).join(' · ')}
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="min-w-[760px] w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  {['Exception', 'PO', 'S-ORD', 'What we see', 'Suggested action'].map((heading) => (
                    <th key={heading} className="px-2 py-2 font-medium">{heading}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {exceptions.length === 0 && (
                  <tr><td colSpan={5} className="px-2 py-4 text-gray-500">No exceptions. Their list matches the open Upwardor purchase orders on the tracker.</td></tr>
                )}
                {exceptions.map((row, index) => {
                  const key = `${row.type}|${row.po_number || ''}|${row.sord || ''}`
                  const fresh = (comparison.new_keys || []).includes(key)
                  return (
                    <tr key={`${key}-${index}`} className="border-t border-gray-100 align-top">
                      <td className="px-2 py-2">
                        {TYPE_LABELS[row.type] || row.type}
                        {fresh && <div className="mt-1 text-xs font-medium text-amber-800">New since last run</div>}
                      </td>
                      <td className="px-2 py-2 whitespace-nowrap">{row.po_number || '—'}</td>
                      <td className="px-2 py-2 whitespace-nowrap">{row.sord || row.our_ack || '—'}</td>
                      <td className="px-2 py-2 text-gray-700">{row.summary}</td>
                      <td className="px-2 py-2 text-gray-700">{row.suggested_action}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}
