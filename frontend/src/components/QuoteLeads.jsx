import { useState, useEffect } from 'react'
import { quoteLeadsApi } from '../api/client'

const STATUS_OPTIONS = ['new', 'contacted', 'quoted', 'won', 'lost']
const STATUS_COLORS = {
  new: 'bg-blue-100 text-blue-800',
  contacted: 'bg-yellow-100 text-yellow-800',
  quoted: 'bg-purple-100 text-purple-800',
  won: 'bg-green-100 text-green-800',
  lost: 'bg-gray-100 text-gray-500',
}

export default function QuoteLeads() {
  const [leads, setLeads] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState(null)
  const [updating, setUpdating] = useState(null)
  const limit = 25

  const loadLeads = async () => {
    setLoading(true)
    try {
      const params = { skip: page * limit, limit }
      if (filter) params.status = filter
      const res = await quoteLeadsApi.list(params)
      setLeads(res.data.leads || [])
      setTotal(res.data.total || 0)
    } catch (err) {
      console.error('Failed to load leads:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadLeads() }, [filter, page])

  const updateStatus = async (leadId, newStatus) => {
    setUpdating(leadId)
    try {
      await quoteLeadsApi.updateStatus(leadId, { status: newStatus })
      setLeads(prev => prev.map(l => l.id === leadId ? { ...l, status: newStatus } : l))
    } catch (err) {
      alert('Failed to update: ' + (err.response?.data?.detail || err.message))
    } finally {
      setUpdating(null)
    }
  }

  const formatDate = (iso) => {
    if (!iso) return '—'
    return new Date(iso).toLocaleDateString('en-CA', {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  }

  const formatDoorSummary = (config) => {
    if (!config) return '—'
    const w = config.widthFeet || Math.floor((config.doorWidth || 0) / 12)
    const h = config.heightFeet || Math.floor((config.doorHeight || 0) / 12)
    const series = config.doorSeries || config.series || ''
    const color = (config.panelColor || config.color || '').replace(/_/g, ' ')
    const design = config.panelDesign || config.design || ''
    return `${series} ${w}'x${h}' ${color} ${design}`.trim()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Quote Leads</h1>
          <p className="text-sm text-gray-500 mt-1">
            Leads from the door designer widget and dealer locator — {total} total
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        <button
          onClick={() => { setFilter(''); setPage(0) }}
          className={`px-3 py-1.5 text-xs font-medium rounded-lg border ${
            !filter ? 'border-odc-500 bg-odc-50 text-odc-700' : 'border-gray-200 text-gray-600 hover:border-gray-300'
          }`}
        >
          All ({total})
        </button>
        {STATUS_OPTIONS.map(s => (
          <button
            key={s}
            onClick={() => { setFilter(s); setPage(0) }}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg border capitalize ${
              filter === s ? 'border-odc-500 bg-odc-50 text-odc-700' : 'border-gray-200 text-gray-600 hover:border-gray-300'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Leads Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-gray-400">Loading leads...</div>
        ) : leads.length === 0 ? (
          <div className="p-12 text-center text-gray-400">
            <p className="text-lg font-medium">No leads yet</p>
            <p className="text-sm mt-1">Leads will appear here when customers submit the door designer widget.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">Date</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">Contact</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">Location</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">Door</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">Source</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">Status</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {leads.map(lead => (
                <tr
                  key={lead.id}
                  className={`hover:bg-gray-50 cursor-pointer ${selected?.id === lead.id ? 'bg-blue-50' : ''}`}
                  onClick={() => setSelected(selected?.id === lead.id ? null : lead)}
                >
                  <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">{formatDate(lead.createdAt)}</td>
                  <td className="px-4 py-3">
                    <p className="font-medium text-gray-900">{lead.name || '—'}</p>
                    <p className="text-xs text-gray-500">{lead.email}</p>
                    {lead.phone && <p className="text-xs text-gray-400">{lead.phone}</p>}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-600">{lead.postalCode || '—'}</td>
                  <td className="px-4 py-3 text-xs text-gray-600">{formatDoorSummary(lead.doorConfig)}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-gray-400 capitalize">{lead.source || 'widget'}</span>
                  </td>
                  <td className="px-4 py-3">
                    <select
                      value={lead.status || 'new'}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => updateStatus(lead.id, e.target.value)}
                      disabled={updating === lead.id}
                      className={`text-xs font-medium px-2 py-1 rounded-full border-0 cursor-pointer ${STATUS_COLORS[lead.status] || STATUS_COLORS.new}`}
                    >
                      {STATUS_OPTIONS.map(s => (
                        <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className="text-xs text-gray-300">{selected?.id === lead.id ? '▼' : '▶'}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Pagination */}
        {total > limit && (
          <div className="px-4 py-3 border-t border-gray-200 flex items-center justify-between">
            <span className="text-xs text-gray-500">
              Showing {page * limit + 1}–{Math.min((page + 1) * limit, total)} of {total}
            </span>
            <div className="flex gap-2">
              <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                className="px-3 py-1 text-xs border border-gray-300 rounded-lg disabled:opacity-50">Prev</button>
              <button onClick={() => setPage(p => p + 1)} disabled={(page + 1) * limit >= total}
                className="px-3 py-1 text-xs border border-gray-300 rounded-lg disabled:opacity-50">Next</button>
            </div>
          </div>
        )}
      </div>

      {/* Lead Detail Panel */}
      {selected && (
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900">Lead Details</h3>
            <button onClick={() => setSelected(null)} className="text-sm text-gray-400 hover:text-gray-600">Close</button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div>
              <p className="text-xs text-gray-500">Name</p>
              <p className="font-medium">{selected.name || '—'}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Email</p>
              <p className="font-medium">{selected.email || '—'}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Phone</p>
              <p className="font-medium">{selected.phone || '—'}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Postal Code</p>
              <p className="font-medium">{selected.postalCode || '—'}</p>
            </div>
          </div>

          {/* Door Preview Image */}
          {selected.doorImage && (
            <div className="mb-6">
              <p className="text-xs text-gray-500 mb-2">Door Design</p>
              <img
                src={selected.doorImage}
                alt="Door design"
                className="max-w-md rounded-lg border border-gray-200 shadow-sm"
              />
            </div>
          )}

          {/* Door Configuration */}
          {selected.doorConfig && (
            <div>
              <p className="text-xs text-gray-500 mb-2">Door Configuration</p>
              <div className="bg-gray-50 rounded-lg p-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                {Object.entries(selected.doorConfig)
                  .filter(([k, v]) => v != null && v !== '' && !['doorImage', 'image'].includes(k))
                  .map(([key, value]) => (
                    <div key={key}>
                      <span className="text-xs text-gray-400">{key.replace(/([A-Z])/g, ' $1').trim()}</span>
                      <p className="font-medium text-gray-700">
                        {typeof value === 'object' ? JSON.stringify(value) : String(value).replace(/_/g, ' ')}
                      </p>
                    </div>
                  ))
                }
              </div>
            </div>
          )}

          {/* Notes */}
          {selected.notes && (
            <div className="mt-4">
              <p className="text-xs text-gray-500 mb-1">Notes</p>
              <p className="text-sm text-gray-700">{selected.notes}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
