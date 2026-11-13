import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { quotesApi } from '../api/client'
import { Link } from 'react-router-dom'

function ReviewQueue() {
  const queryClient = useQueryClient()
  const { data: quotes, isLoading, refetch } = useQuery({
    queryKey: ['pendingQuotes'],
    queryFn: async () => {
      const response = await quotesApi.getPendingReviews({ status: 'pending' })
      return response.data
    },
  })

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-gray-500">Loading quotes...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PurchaseOrderReviews onChanged={() => queryClient.invalidateQueries({ queryKey: ['quote-po-intakes'] })} />
      <div className="sm:flex sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Review Queue</h1>
          <p className="mt-2 text-sm text-gray-700">
            {quotes?.length || 0} quote{quotes?.length !== 1 ? 's' : ''} pending review
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="mt-4 sm:mt-0 inline-flex items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50"
        >
          <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh
        </button>
      </div>

      <div className="bg-white shadow overflow-hidden sm:rounded-lg">
        {quotes && quotes.length > 0 ? (
          <ul className="divide-y divide-gray-200">
            {quotes.map((quote) => (
              <QuoteListItem key={quote.id} quote={quote} />
            ))}
          </ul>
        ) : (
          <div className="text-center py-12">
            <p className="text-gray-500">No quotes pending review</p>
          </div>
        )}
      </div>
      <CustomerApprovals onChanged={() => queryClient.invalidateQueries({ queryKey: ['customer-approvals'] })} />
    </div>
  )
}

function PurchaseOrderReviews({ onChanged }) {
  const { data, refetch } = useQuery({
    queryKey: ['quote-po-intakes'],
    queryFn: async () => (await quotesApi.getQuotePoIntakes()).data,
  })
  const rows = data || []
  const missed = rows.filter((row) => row.overdue)
  const [choice, setChoice] = useState({})
  const [note, setNote] = useState('')
  if (!rows.length) return null
  async function accept(row) {
    const picked = choice[row.id] || row.bc_quote_number
    if (!picked) {
      setNote('Choose the quote to convert')
      return
    }
    if (!window.confirm(`Convert ${picked} to a sales order for PO ${row.customer_po || ''}?`)) return
    try {
      const response = await quotesApi.acceptQuotePo(row.id, picked)
      const created = response.data.bc_order_number
      setNote(response.data.detail || (created ? `Created ${created}` : 'Saved'))
      refetch()
      onChanged()
    } catch (err) {
      setNote(err.response?.data?.detail || 'Could not convert')
    }
  }
  async function dismiss(row) {
    if (!window.confirm('Dismiss this purchase order email?')) return
    try {
      await quotesApi.dismissQuotePo(row.id)
      setNote('Dismissed')
      refetch()
      onChanged()
    } catch (err) {
      setNote(err.response?.data?.detail || 'Could not dismiss')
    }
  }
  return (
    <div className="bg-white shadow rounded-lg p-6 space-y-3" data-testid="quote-po-queue">
      {missed.length > 0 && (
        <div className="rounded-md border border-red-300 bg-red-50 p-4" data-testid="missed-po-banner">
          <p className="text-sm font-medium text-red-900">
            {missed.length} purchase order email{missed.length === 1 ? '' : 's'} older than 4 business hours with no sales order
          </p>
          <ul className="mt-2 space-y-1 text-sm text-red-800">
            {missed.map((row) => (
              <li key={row.id}>
                PO {row.customer_po || '—'} from {row.from_address || 'unknown sender'}
                {row.bc_quote_number ? ` · ${row.bc_quote_number}` : ''}
                {row.subject ? ` · ${row.subject}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      <h2 className="text-lg font-medium text-gray-900">Customer purchase orders</h2>
      <p className="text-sm text-gray-600">
        A high-confidence match converts on its own when the switch is on. Everything else waits here. Shadow does not call Business Central.
      </p>
      {note && <p className="text-sm text-gray-800">{note}</p>}
      {rows.map((row) => (
        <div key={row.id} className={`border rounded-md p-4 space-y-2 ${row.overdue ? 'border-red-300' : 'border-gray-200'}`}>
          <p className="text-sm font-medium text-gray-900">{row.subject || row.from_address}</p>
          <p className="text-sm text-gray-600">
            {row.from_address || 'Unknown sender'}
            {row.customer_po ? ` · PO ${row.customer_po}` : ''}
            {row.bc_quote_number ? ` · ${row.bc_quote_number}` : ''}
            {row.status === 'shadow' ? ' · Shadow' : ''}
            {row.overdue ? ' · No sales order after 4 business hours' : ''}
          </p>
          {row.review_reason_text && <p className="text-sm text-amber-800">{row.review_reason_text}</p>}
          {row.planned_action && <p className="text-sm text-gray-700">{row.planned_action}</p>}
          {row.excerpt && (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-3 text-sm text-gray-800">{row.excerpt}</pre>
          )}
          <label className="block text-sm text-gray-700">
            Quote
            <input
              aria-label={`Quote for purchase order ${row.id}`}
              list={`po-quotes-${row.id}`}
              value={choice[row.id] ?? row.bc_quote_number ?? ''}
              onChange={(event) => setChoice({ ...choice, [row.id]: event.target.value })}
              className="mt-1 block w-full max-w-xs border border-gray-300 rounded-md px-2 py-1 text-sm"
            />
            <datalist id={`po-quotes-${row.id}`}>
              {(row.candidates || []).map((item) => (
                <option key={item.bc_quote_number} value={item.bc_quote_number}>{item.customer_name || item.bc_quote_number}</option>
              ))}
            </datalist>
          </label>
          <div className="flex gap-2">
            <button type="button" onClick={() => accept(row)} className="inline-flex items-center px-3 py-1.5 rounded-md text-sm font-medium text-white bg-odc-600">
              Convert to SO
            </button>
            <button type="button" onClick={() => dismiss(row)} className="inline-flex items-center px-3 py-1.5 rounded-md text-sm font-medium text-gray-700 border border-gray-300">
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

function CustomerApprovals({ onChanged }) {
  const { data, refetch } = useQuery({
    queryKey: ['customer-approvals'],
    queryFn: async () => (await quotesApi.getCustomerApprovals()).data,
  })
  const rows = (data || []).filter((row) => row.status === 'ready' || row.status === 'partial' || row.status === 'needs_choice')
  const [choice, setChoice] = useState({})
  const [note, setNote] = useState('')
  if (!rows.length) return null
  async function convert(row) {
    const picked = row.status === 'needs_choice' ? choice[row.id] : row.bc_quote_number
    if (!picked) return
    const exception = row.confidence === 'partial' && row.exception_text
      ? `\n\nThis is a partial approval. Exception: ${row.exception_text}`
      : ''
    if (!window.confirm(`Convert ${picked} to a sales order? This is not undone from here.${exception}`)) return
    try {
      const response = await quotesApi.convertCustomerApproval(row.id, picked)
      setNote(response.data.bc_order_number ? `Created ${response.data.bc_order_number}` : 'Converted')
      refetch()
      onChanged()
    } catch (err) {
      setNote(err.response?.data?.detail || 'Could not convert')
    }
  }
  return (
    <div className="bg-white shadow rounded-lg p-6 space-y-3" data-testid="approval-queue">
      <h2 className="text-lg font-medium text-gray-900">Customer approvals</h2>
      <p className="text-sm text-gray-600">A go-ahead is waiting. Convert is a click. Nothing happens until then.</p>
      {note && <p className="text-sm text-gray-800">{note}</p>}
      {rows.map((row) => (
        <div key={row.id} className="border border-gray-200 rounded-md p-4 space-y-2">
          <p className="text-sm font-medium text-gray-900">{row.subject || row.from_address}</p>
          <p className="text-sm text-gray-600">
            {row.status === 'needs_choice' ? 'Choose a quote' : `Matched ${row.bc_quote_number}`}
            {row.status === 'partial' ? ' · Partial approval' : ''}
            {row.customer_po ? ` · PO ${row.customer_po}` : ''}
          </p>
          {row.excerpt && <p className="text-sm text-gray-800 whitespace-pre-wrap">{row.excerpt}</p>}
          {row.status === 'needs_choice' && (
            <select aria-label={`Quote for approval ${row.id}`} value={choice[row.id] || ''} onChange={(event) => setChoice({ ...choice, [row.id]: event.target.value })} className="border border-gray-300 rounded-md px-2 py-1 text-sm">
              <option value="">Choose a quote</option>
              {(row.candidates || []).map((item) => (
                <option key={item.bc_quote_number} value={item.bc_quote_number}>{item.bc_quote_number}</option>
              ))}
            </select>
          )}
          <button type="button" onClick={() => convert(row)} className="inline-flex items-center px-3 py-1.5 rounded-md text-sm font-medium text-white bg-odc-600">
            Convert to SO
          </button>
        </div>
      ))}
    </div>
  )
}

function QuoteListItem({ quote }) {
  const confidence = quote.confidence_scores?.overall || 0
  const confidencePercent = (confidence * 100).toFixed(0)

  const getConfidenceColor = (confidence) => {
    if (confidence >= 0.8) return 'bg-green-100 text-green-800'
    if (confidence >= 0.6) return 'bg-yellow-100 text-yellow-800'
    return 'bg-red-100 text-red-800'
  }

  const doorCount = quote.parsed_data?.doors?.length || 0

  return (
    <li>
      <Link to={`/reviews/${quote.id}`} className="block hover:bg-gray-50">
        <div className="px-4 py-4 sm:px-6">
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <p className="text-sm font-medium text-odc-600 truncate">
                {quote.customer_name || 'Unknown Customer'}
              </p>
              <div className="mt-2 flex items-center text-sm text-gray-500">
                <svg className="flex-shrink-0 mr-1.5 h-5 w-5 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M2.003 5.884L10 9.882l7.997-3.998A2 2 0 0016 4H4a2 2 0 00-1.997 1.884z" />
                  <path d="M18 8.118l-8 4-8-4V14a2 2 0 002 2h12a2 2 0 002-2V8.118z" />
                </svg>
                <span className="truncate">{quote.contact_email || 'No email'}</span>
              </div>
              <div className="mt-2 flex items-center text-sm text-gray-500">
                <span>{doorCount} door{doorCount !== 1 ? 's' : ''}</span>
                <span className="mx-2">•</span>
                <span>{quote.email_subject || 'No subject'}</span>
              </div>
            </div>
            <div className="ml-4 flex-shrink-0 flex flex-col items-end space-y-2">
              <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${getConfidenceColor(confidence)}`}>
                {confidencePercent}% confidence
              </span>
              <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                {quote.status}
              </span>
            </div>
          </div>
        </div>
      </Link>
    </li>
  )
}

export default ReviewQueue
