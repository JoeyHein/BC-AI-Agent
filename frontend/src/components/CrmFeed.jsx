import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { customersApi } from '../api/client'

const TYPE_META = {
  call:    { label: 'Call',    badge: 'bg-blue-100 text-blue-800' },
  email:   { label: 'Email',   badge: 'bg-purple-100 text-purple-800' },
  meeting: { label: 'Meeting', badge: 'bg-emerald-100 text-emerald-800' },
  sms:     { label: 'SMS',     badge: 'bg-amber-100 text-amber-800' },
}

/**
 * CrmFeed — global reverse-chronological list of every note Donna and other
 * agents have logged. Drop-in component used by the Activity tab on the
 * Customer Management page.
 *
 * `matchedFilter` can be 'all', 'matched' (linked to a BC customer), or
 * 'unmatched' (needs triage). The triage view shows a "Link to customer"
 * button inline so calls from unrecognized numbers can be assigned.
 */
export default function CrmFeed({ matchedFilter = 'all', customers = [] }) {
  const [typeFilter, setTypeFilter] = useState('all')

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['crm-feed', matchedFilter, typeFilter],
    queryFn: async () => {
      const r = await customersApi.getNotesFeed({
        note_type: typeFilter,
        matched: matchedFilter,
        limit: 100,
      })
      return r.data
    },
    refetchInterval: 30_000,
  })

  const notes = data?.notes || []

  return (
    <div className="bg-white shadow rounded-lg">
      <div className="px-4 py-3 border-b flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">
            {matchedFilter === 'unmatched' ? 'Unmatched Conversations' : 'All Conversations'}
          </h2>
          <p className="text-xs text-gray-500">
            {matchedFilter === 'unmatched'
              ? 'Calls, emails, or messages from numbers not yet linked to a BC customer. Assign each to a customer to file it.'
              : 'Every interaction Donna has logged — calls, emails, and SMS.'}
          </p>
        </div>
        <div className="flex gap-1">
          {['all', 'call', 'email', 'meeting', 'sms'].map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                typeFilter === t
                  ? 'bg-odc-600 text-white border-odc-600'
                  : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
              }`}
            >
              {t === 'all' ? 'All' : TYPE_META[t]?.label || t}
            </button>
          ))}
        </div>
      </div>

      <div className="p-4">
        {isLoading ? (
          <div className="text-sm text-gray-400 py-6 text-center">Loading…</div>
        ) : notes.length === 0 ? (
          <div className="text-sm text-gray-400 py-10 text-center">
            {matchedFilter === 'unmatched'
              ? 'Nothing unmatched — every logged conversation is linked to a customer.'
              : 'No conversations yet. Notes appear here automatically when Donna handles a call, email, or SMS.'}
          </div>
        ) : (
          <ul className="space-y-3">
            {notes.map((n) => (
              <NoteRow key={n.id} note={n} customers={customers} onLinked={refetch} />
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function NoteRow({ note, customers, onLinked }) {
  const [open, setOpen] = useState(false)
  const [showLink, setShowLink] = useState(false)
  const meta = TYPE_META[note.note_type] || { label: note.note_type, badge: 'bg-gray-100 text-gray-700' }
  const bodyPreview = note.body.length > 180 ? note.body.slice(0, 180) + '…' : note.body
  const createdAt = note.created_at ? new Date(note.created_at) : null

  return (
    <li className="border border-gray-200 rounded-lg">
      <div className="flex items-start gap-3 p-3">
        <span className={`shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded ${meta.badge}`}>
          {meta.label.toUpperCase()}
        </span>
        <button
          onClick={() => setOpen(!open)}
          className="flex-1 min-w-0 text-left"
        >
          <div className="flex items-center gap-2 flex-wrap">
            {note.customer_name ? (
              <span className="text-sm font-medium text-gray-900">{note.customer_name}</span>
            ) : (
              <span className="text-sm font-medium text-amber-700">Unmatched · {note.match_key}</span>
            )}
            {note.subject && <span className="text-sm text-gray-700">· {note.subject}</span>}
          </div>
          <p className="text-sm text-gray-600 whitespace-pre-wrap line-clamp-2 mt-0.5">
            {open ? note.body : bodyPreview}
          </p>
          <div className="mt-1 flex items-center gap-2 text-xs text-gray-400 flex-wrap">
            <span>{note.source}</span>
            {createdAt && <span>· {createdAt.toLocaleString()}</span>}
            {note.metadata?.duration_seconds != null && (
              <span>· {Math.floor(note.metadata.duration_seconds / 60)}m {note.metadata.duration_seconds % 60}s</span>
            )}
            {note.metadata?.answered_by_donna && <span className="text-odc-600">· Donna answered</span>}
          </div>
        </button>
        {!note.bc_customer_id && (
          <button
            onClick={() => setShowLink(true)}
            className="shrink-0 text-xs px-2 py-1 rounded bg-odc-600 text-white hover:bg-odc-700"
            title="Assign this note to a BC customer"
          >
            Link…
          </button>
        )}
      </div>

      {open && note.body.length > 180 && (
        <div className="px-3 pb-3 pt-0">
          <pre className="whitespace-pre-wrap text-sm text-gray-700 font-sans bg-gray-50 rounded p-3 max-h-96 overflow-auto">
            {note.body}
          </pre>
        </div>
      )}

      {showLink && (
        <LinkToCustomerModal
          note={note}
          customers={customers}
          onClose={() => setShowLink(false)}
          onLinked={() => {
            setShowLink(false)
            onLinked?.()
          }}
        />
      )}
    </li>
  )
}

function LinkToCustomerModal({ note, customers, onClose, onLinked }) {
  const [search, setSearch] = useState('')
  const queryClient = useQueryClient()

  const link = useMutation({
    mutationFn: (bcCustomerId) => customersApi.linkNoteToCustomer(note.id, bcCustomerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['crm-feed'] })
      queryClient.invalidateQueries({ queryKey: ['customer-notes'] })
      onLinked?.()
    },
  })

  const filtered = customers
    .filter((c) => c.bc_customer_id)
    .filter((c) => {
      const s = search.toLowerCase()
      if (!s) return true
      return (
        c.bc_company_name?.toLowerCase().includes(s) ||
        c.name?.toLowerCase().includes(s) ||
        c.email?.toLowerCase().includes(s) ||
        c.bc_customer_id?.toLowerCase().includes(s)
      )
    })
    .slice(0, 50)

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-md max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b">
          <h3 className="text-lg font-semibold">Link to customer</h3>
          <p className="text-xs text-gray-500 mt-1">
            {note.subject || `${note.note_type} from ${note.match_key}`}
          </p>
        </div>
        <div className="p-4 border-b">
          <input
            autoFocus
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by company, name, or email…"
            className="w-full border border-gray-200 rounded px-3 py-2 text-sm"
          />
        </div>
        <div className="flex-1 overflow-y-auto">
          {filtered.length === 0 ? (
            <p className="text-sm text-gray-400 p-4 text-center">No matching customers.</p>
          ) : (
            <ul>
              {filtered.map((c) => (
                <li key={c.id}>
                  <button
                    onClick={() => link.mutate(c.bc_customer_id)}
                    disabled={link.isPending}
                    className="w-full text-left px-4 py-2 hover:bg-gray-50 disabled:opacity-50 border-b border-gray-100 last:border-0"
                  >
                    <p className="text-sm font-medium text-gray-900">
                      {c.bc_company_name || c.name || c.email}
                    </p>
                    <p className="text-xs text-gray-500">
                      {c.bc_customer_id} {c.email && `· ${c.email}`}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="p-3 border-t flex justify-end">
          <button onClick={onClose} className="text-sm text-gray-600 hover:text-gray-800 px-3 py-1.5">
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
