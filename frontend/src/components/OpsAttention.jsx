import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { opsApi } from '../api/client'

function OpsAttention() {
  const actions = useQuery({
    queryKey: ['ops-actions'],
    queryFn: async () => (await opsApi.actions('open')).data,
  })
  const messages = useQuery({
    queryKey: ['ops-messages', 'pending'],
    queryFn: async () => (await opsApi.messages('pending')).data,
  })

  if (actions.isError && messages.isError) return null

  const rows = actions.data?.actions || []
  const overdue = rows.filter((row) => row.overdue)
  const pending = messages.data?.messages?.length || 0
  const shown = (overdue.length ? overdue : rows).slice(0, 5)

  return (
    <section className="rounded-2xl bg-white p-4 ring-1 ring-gray-200">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Needs attention</h2>
          <p className="text-xs text-gray-500">Replies, missing purchase orders, acknowledgements, and follow-ups.</p>
        </div>
        <div className="flex gap-2 text-xs font-medium">
          <Link to="/production?tab=todo" className="rounded-full bg-odc-900 px-3 py-1 text-white">
            {rows.length} open
          </Link>
          <Link to="/production?tab=approvals" className="rounded-full bg-amber-100 px-3 py-1 text-amber-900">
            {pending} to approve
          </Link>
        </div>
      </div>
      {actions.data?.mail && actions.data.mail.available === false && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">{actions.data.mail.reason}</p>
      )}
      <ul className="mt-3 divide-y divide-gray-100">
        {shown.length === 0 && <li className="py-2 text-sm text-gray-500">Nothing open.</li>}
        {shown.map((row) => (
          <li key={row.id} className="flex items-start justify-between gap-3 py-2">
            <div>
              <p className="text-sm text-gray-900">{row.title}</p>
              <p className="text-xs text-gray-500">{row.detail}</p>
            </div>
            {row.overdue && <span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">Overdue</span>}
          </li>
        ))}
      </ul>
    </section>
  )
}

export default OpsAttention
