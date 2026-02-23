import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { savedQuotesApi, bcQuotesApi } from '../../api/customerClient'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'
import QuotePricingDisplay from './QuotePricingDisplay'

function SavedQuotes() {
  const [filter, setFilter] = useState('all') // all, draft, submitted
  const [pricingState, setPricingState] = useState({}) // { [quoteId]: { loading, data, error } }
  const [downloadingPdf, setDownloadingPdf] = useState({}) // { [quoteId]: boolean }
  const { isBCLinked } = useCustomerAuth()
  const queryClient = useQueryClient()

  const { data: quotes, isLoading, error } = useQuery({
    queryKey: ['savedQuotes'],
    queryFn: async () => {
      const response = await savedQuotesApi.getAll()
      return response.data
    }
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => savedQuotesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['savedQuotes'])
    }
  })

  const confirmMutation = useMutation({
    mutationFn: (id) => savedQuotesApi.confirm(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['savedQuotes'])
    }
  })

  const submitMutation = useMutation({
    mutationFn: (id) => savedQuotesApi.submit(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['savedQuotes'])
    }
  })

  const placeOrderMutation = useMutation({
    mutationFn: (id) => savedQuotesApi.placeOrder(id),
    onSuccess: (response) => {
      queryClient.invalidateQueries(['savedQuotes'])
      queryClient.invalidateQueries(['orders'])
      const data = response.data
      alert(`Order placed successfully!\n\nOrder Number: ${data.bc_order_number}${data.total_amount ? `\nTotal: $${data.total_amount.toLocaleString('en-US', { minimumFractionDigits: 2 })} CAD` : ''}`)
    },
    onError: (err) => {
      alert(`Failed to place order: ${err.response?.data?.detail || err.message}`)
    }
  })

  const handleDelete = async (id, name) => {
    if (window.confirm(`Are you sure you want to delete "${name || 'this quote'}"?`)) {
      deleteMutation.mutate(id)
    }
  }

  const handleGetPricing = async (id) => {
    if (!isBCLinked) {
      alert('Your account must be linked to get pricing. Please contact support.')
      return
    }

    setPricingState(prev => ({
      ...prev,
      [id]: { loading: true, data: null, error: null }
    }))

    try {
      const response = await savedQuotesApi.getPricing(id)
      setPricingState(prev => ({
        ...prev,
        [id]: { loading: false, data: response.data, error: null }
      }))
      queryClient.invalidateQueries(['savedQuotes'])
    } catch (error) {
      setPricingState(prev => ({
        ...prev,
        [id]: { loading: false, data: null, error: error.response?.data?.detail || 'Failed to get pricing' }
      }))
    }
  }

  const handleConfirm = async (id, name) => {
    if (window.confirm(`Confirm and submit "${name || 'this quote'}"? This cannot be undone.`)) {
      confirmMutation.mutate(id)
    }
  }

  const handleSubmit = async (id, name) => {
    if (!isBCLinked) {
      alert('Your account must be linked to submit quotes. Please contact support.')
      return
    }
    if (window.confirm(`Submit "${name || 'this quote'}" for processing? This cannot be undone.`)) {
      submitMutation.mutate(id)
    }
  }

  const handlePlaceOrder = (id, name) => {
    if (window.confirm(`Place an order for "${name || 'this quote'}"?\n\nThis will convert the quote into a sales order in Business Central. This action cannot be undone.`)) {
      placeOrderMutation.mutate(id)
    }
  }

  const handleDownloadPdf = async (quoteId, bcQuoteId, quoteNumber) => {
    setDownloadingPdf(prev => ({ ...prev, [quoteId]: true }))
    try {
      const response = await bcQuotesApi.getPdf(bcQuoteId)
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `Quote_${quoteNumber || quoteId}.pdf`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      alert('Failed to download quote PDF')
    } finally {
      setDownloadingPdf(prev => ({ ...prev, [quoteId]: false }))
    }
  }

  const filteredQuotes = quotes?.filter(q => {
    if (filter === 'draft') return !q.is_submitted
    if (filter === 'submitted') return q.is_submitted
    return true
  }) || []

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 p-4 rounded-md">
        <p className="text-red-700">Failed to load saved quotes. Please try again.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">My Quotes</h1>
          <p className="mt-1 text-sm text-gray-500">
            Save door configurations and submit them when ready
          </p>
        </div>
        <Link
          to="new"
          className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
        >
          <PlusIcon className="h-5 w-5 mr-2" />
          New Quote
        </Link>
      </div>

      {/* Filter tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          {[
            { key: 'all', label: 'All', count: quotes?.length || 0 },
            { key: 'draft', label: 'Drafts', count: quotes?.filter(q => !q.is_submitted).length || 0 },
            { key: 'submitted', label: 'Submitted', count: quotes?.filter(q => q.is_submitted).length || 0 },
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={`whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm ${
                filter === tab.key
                  ? 'border-odc-500 text-odc-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {tab.label}
              <span className={`ml-2 py-0.5 px-2.5 rounded-full text-xs ${
                filter === tab.key ? 'bg-blue-100 text-odc-600' : 'bg-gray-100 text-gray-900'
              }`}>
                {tab.count}
              </span>
            </button>
          ))}
        </nav>
      </div>

      {/* Quotes list */}
      {filteredQuotes.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <DocumentIcon className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-2 text-sm font-medium text-gray-900">No quotes</h3>
          <p className="mt-1 text-sm text-gray-500">
            {filter === 'all'
              ? 'Get started by creating a new quote.'
              : `No ${filter} quotes found.`}
          </p>
          {filter === 'all' && (
            <div className="mt-6">
              <Link
                to="new"
                className="inline-flex items-center px-4 py-2 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700"
              >
                <PlusIcon className="-ml-1 mr-2 h-5 w-5" />
                New Quote
              </Link>
            </div>
          )}
        </div>
      ) : (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <ul className="divide-y divide-gray-200">
            {filteredQuotes.map((quote) => (
              <li key={quote.id}>
                <div className="px-4 py-4 sm:px-6 hover:bg-gray-50">
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <Link to={`${quote.id}`} className="block">
                        <p className="text-sm font-medium text-odc-600 truncate hover:text-blue-800">
                          {quote.name || 'Unnamed Quote'}
                        </p>
                        <p className="mt-1 text-sm text-gray-500">
                          {quote.description || 'No description'}
                        </p>
                      </Link>
                    </div>
                    <div className="ml-4 flex-shrink-0 flex items-center space-x-4">
                      <div className="text-right">
                        <p className="text-sm text-gray-500">
                          Created: {new Date(quote.created_at).toLocaleDateString()}
                        </p>
                        {quote.updated_at && (
                          <p className="text-xs text-gray-400">
                            Updated: {new Date(quote.updated_at).toLocaleDateString()}
                          </p>
                        )}
                      </div>

                      {quote.is_submitted ? (
                        <div className="flex items-center space-x-2">
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                            Submitted
                            {quote.bc_quote_number && ` - ${quote.bc_quote_number}`}
                          </span>
                          {quote.bc_quote_id && (
                            <>
                              <button
                                onClick={() => handlePlaceOrder(quote.id, quote.name)}
                                disabled={placeOrderMutation.isPending}
                                className="inline-flex items-center px-3 py-1 border border-transparent text-xs font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
                              >
                                {placeOrderMutation.isPending ? 'Placing...' : 'Place Order'}
                              </button>
                              <button
                                onClick={() => handleDownloadPdf(quote.id, quote.bc_quote_id, quote.bc_quote_number)}
                                disabled={downloadingPdf[quote.id]}
                                className="inline-flex items-center px-3 py-1 border border-gray-300 text-xs font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                              >
                                {downloadingPdf[quote.id] ? 'Downloading...' : 'Download PDF'}
                              </button>
                            </>
                          )}
                        </div>
                      ) : quote.bc_quote_id ? (
                        /* Priced but not yet submitted */
                        <div className="flex items-center space-x-2">
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                            Priced
                            {quote.bc_quote_number && ` - ${quote.bc_quote_number}`}
                          </span>
                          <button
                            onClick={() => handleConfirm(quote.id, quote.name)}
                            disabled={confirmMutation.isPending}
                            className="inline-flex items-center px-3 py-1 border border-transparent text-xs font-medium rounded-md text-white bg-green-600 hover:bg-green-700 disabled:opacity-50"
                          >
                            Confirm & Submit
                          </button>
                          <button
                            onClick={() => handlePlaceOrder(quote.id, quote.name)}
                            disabled={placeOrderMutation.isPending}
                            className="inline-flex items-center px-3 py-1 border border-transparent text-xs font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
                          >
                            {placeOrderMutation.isPending ? 'Placing...' : 'Place Order'}
                          </button>
                          <button
                            onClick={() => handleGetPricing(quote.id)}
                            disabled={pricingState[quote.id]?.loading}
                            className="inline-flex items-center px-3 py-1 border border-blue-300 text-xs font-medium rounded-md text-odc-700 bg-white hover:bg-blue-50 disabled:opacity-50"
                          >
                            Refresh Pricing
                          </button>
                          <button
                            onClick={() => handleDownloadPdf(quote.id, quote.bc_quote_id, quote.bc_quote_number)}
                            disabled={downloadingPdf[quote.id]}
                            className="inline-flex items-center px-3 py-1 border border-gray-300 text-xs font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                          >
                            {downloadingPdf[quote.id] ? 'Downloading...' : 'Download PDF'}
                          </button>
                          <button
                            onClick={() => handleDelete(quote.id, quote.name)}
                            disabled={deleteMutation.isPending}
                            className="inline-flex items-center px-3 py-1 border border-gray-300 text-xs font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                          >
                            Delete
                          </button>
                        </div>
                      ) : (
                        /* Draft - no pricing yet */
                        <div className="flex items-center space-x-2">
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
                            Draft
                          </span>
                          {isBCLinked && (
                            <button
                              onClick={() => handleGetPricing(quote.id)}
                              disabled={pricingState[quote.id]?.loading}
                              className="inline-flex items-center px-3 py-1 border border-transparent text-xs font-medium rounded-md text-white bg-green-600 hover:bg-green-700 disabled:opacity-50"
                            >
                              {pricingState[quote.id]?.loading ? 'Getting Pricing...' : 'Get Pricing'}
                            </button>
                          )}
                          <button
                            onClick={() => handleSubmit(quote.id, quote.name)}
                            disabled={submitMutation.isPending}
                            className="inline-flex items-center px-3 py-1 border border-blue-300 text-xs font-medium rounded-md text-odc-700 bg-white hover:bg-blue-50 disabled:opacity-50"
                          >
                            Submit
                          </button>
                          <button
                            onClick={() => handleDelete(quote.id, quote.name)}
                            disabled={deleteMutation.isPending}
                            className="inline-flex items-center px-3 py-1 border border-gray-300 text-xs font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Config preview */}
                  {quote.config_data && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {/* New multi-door format */}
                      {quote.config_data.doors ? (
                        <>
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                            {quote.config_data.doors.length} door{quote.config_data.doors.length > 1 ? 's' : ''}
                          </span>
                          {quote.config_data.doors[0]?.doorSeries && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
                              {quote.config_data.doors[0].doorSeries}
                            </span>
                          )}
                          {quote.config_data.doors[0]?.doorWidth && quote.config_data.doors[0]?.doorHeight && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
                              {Math.floor(quote.config_data.doors[0].doorWidth / 12)}' x {Math.floor(quote.config_data.doors[0].doorHeight / 12)}'
                            </span>
                          )}
                          {quote.config_data.doors[0]?.panelColor && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
                              {quote.config_data.doors[0].panelColor}
                            </span>
                          )}
                        </>
                      ) : (
                        <>
                          {/* Legacy single door format */}
                          {quote.config_data.door_type && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
                              {quote.config_data.door_type}
                            </span>
                          )}
                          {quote.config_data.width && quote.config_data.height && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
                              {quote.config_data.width}" x {quote.config_data.height}"
                            </span>
                          )}
                          {quote.config_data.color && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
                              {quote.config_data.color}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  )}

                  {/* Pricing display (from get-pricing action) */}
                  {pricingState[quote.id]?.data?.pricing && (
                    <div className="mt-2">
                      <QuotePricingDisplay
                        pricing={pricingState[quote.id].data.pricing}
                        linePricing={pricingState[quote.id].data.line_pricing}
                        linesFailed={pricingState[quote.id].data.lines_failed}
                        bcQuoteNumber={pricingState[quote.id].data.bc_quote_number}
                        doorResults={pricingState[quote.id].data.door_results}
                        compact={true}
                      />
                    </div>
                  )}

                  {/* Pricing error */}
                  {pricingState[quote.id]?.error && (
                    <div className="mt-2 bg-red-50 border border-red-200 rounded p-2">
                      <p className="text-xs text-red-700">{pricingState[quote.id].error}</p>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function PlusIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
    </svg>
  )
}

function DocumentIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
    </svg>
  )
}

export default SavedQuotes
