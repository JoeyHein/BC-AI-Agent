import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { adminQuotesApi } from '../api/client'

function statusBadge(q) {
  if (q.order_placed) return { text: 'Ordered', cls: 'bg-gray-200 text-gray-800' }
  if (q.is_submitted) return { text: 'Submitted', cls: 'bg-green-100 text-green-800' }
  if (q.bc_quote_id) return { text: 'Priced', cls: 'bg-blue-100 text-blue-800' }
  return { text: 'Draft', cls: 'bg-yellow-100 text-yellow-800' }
}

function QuoteSearch() {
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 250)
    return () => clearTimeout(t)
  }, [searchInput])

  const { data: quotes, isLoading } = useQuery({
    queryKey: ['admin-quote-search', search],
    queryFn: async () => {
      const r = await adminQuotesApi.search(search ? { search, limit: 100 } : { limit: 50 })
      return r.data
    },
  })

  const list = quotes || []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Quotes</h1>
          <p className="mt-1 text-sm text-gray-500">
            Search any saved quote across all customers by quote # or tag name.
          </p>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg p-4">
        <div className="relative max-w-lg">
          <input
            type="text"
            autoFocus
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search by quote # or tag name…"
            className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-odc-500 focus:border-odc-500"
          />
          <svg className="absolute left-3 top-2.5 h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M11 19a8 8 0 100-16 8 8 0 000 16z" />
          </svg>
          {searchInput && (
            <button
              onClick={() => setSearchInput('')}
              className="absolute right-2 top-2 text-gray-400 hover:text-gray-600 px-1"
              aria-label="Clear search"
            >
              ×
            </button>
          )}
        </div>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="p-6 text-sm text-gray-400">Loading…</div>
          ) : list.length === 0 ? (
            <div className="p-8 text-center text-sm text-gray-400">
              {search ? 'No quotes match your search.' : 'No quotes yet.'}
            </div>
          ) : (
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">BC Quote #</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tag / Name</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Customer</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {list.map((q) => {
                  const b = statusBadge(q)
                  return (
                    <tr key={q.id} className="hover:bg-gray-50">
                      <td className="px-6 py-3 text-sm font-mono text-gray-700">
                        {q.bc_quote_number || <span className="text-gray-400">—</span>}
                      </td>
                      <td className="px-6 py-3 text-sm text-gray-900">
                        {q.name || <span className="text-gray-400">(untitled)</span>}
                      </td>
                      <td className="px-6 py-3 text-sm">
                        <Link
                          to={`/customers/${q.customer.id}`}
                          className="text-odc-600 hover:text-odc-800 font-medium"
                        >
                          {q.customer.company_name || q.customer.name || q.customer.email}
                        </Link>
                        <p className="text-xs text-gray-500">{q.customer.email}</p>
                      </td>
                      <td className="px-6 py-3">
                        <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${b.cls}`}>
                          {b.text}
                        </span>
                      </td>
                      <td className="px-6 py-3 text-sm text-gray-500">
                        {q.created_at ? new Date(q.created_at).toLocaleDateString() : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

export default QuoteSearch
