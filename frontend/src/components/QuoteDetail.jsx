import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { quotesApi, emailFeedbackApi } from '../api/client'
import { useState } from 'react'

function QuoteDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [notes, setNotes] = useState('')
  const [showQuote, setShowQuote] = useState(false)

  const { data: quote, isLoading } = useQuery({
    queryKey: ['quote', id],
    queryFn: async () => {
      const response = await quotesApi.getQuote(id)
      return response.data
    },
  })

  const { data: quoteData, isLoading: quoteLoading } = useQuery({
    queryKey: ['quoteGenerated', id],
    queryFn: async () => {
      const response = await quotesApi.getQuoteItems(id)
      return response.data
    },
    enabled: showQuote,
  })

  const approveMutation = useMutation({
    mutationFn: () => quotesApi.approveQuote(id, { notes }),
    onSuccess: () => {
      queryClient.invalidateQueries(['quote', id])
      queryClient.invalidateQueries(['pendingQuotes'])
      queryClient.invalidateQueries(['allQuotes'])
      queryClient.invalidateQueries(['quoteStats'])
      queryClient.invalidateQueries(['learningProgress'])
      alert('Quote approved successfully!')
      navigate('/reviews')
    },
  })

  const rejectMutation = useMutation({
    mutationFn: () => quotesApi.rejectQuote(id, notes || 'No reason provided'),
    onSuccess: () => {
      queryClient.invalidateQueries(['quote', id])
      queryClient.invalidateQueries(['pendingQuotes'])
      queryClient.invalidateQueries(['allQuotes'])
      queryClient.invalidateQueries(['quoteStats'])
      alert('Quote rejected')
      navigate('/reviews')
    },
  })

  const generateQuoteMutation = useMutation({
    mutationFn: () => quotesApi.generateQuote(id),
    onSuccess: () => {
      setShowQuote(true)
      queryClient.invalidateQueries(['quoteGenerated', id])
      alert('Quote generated successfully!')
    },
  })

  const markNotQuoteMutation = useMutation({
    mutationFn: () => {
      // Get the email_id from the quote object
      const emailId = quote?.email_id
      if (!emailId) {
        throw new Error('Email ID not found')
      }
      return emailFeedbackApi.markAsNotQuote(emailId)
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries(['quote', id])
      queryClient.invalidateQueries(['pendingQuotes'])
      queryClient.invalidateQueries(['allQuotes'])
      queryClient.invalidateQueries(['quoteStats'])
      queryClient.invalidateQueries(['categorizationStats'])
      alert('Marked as "Not a Quote Request" - AI will learn from this!')
      navigate('/reviews')
    },
  })

  const createBCQuoteMutation = useMutation({
    mutationFn: () => quotesApi.createBCQuote(parseInt(id)),
    onSuccess: (response) => {
      queryClient.invalidateQueries(['quote', id])
      queryClient.invalidateQueries(['pendingQuotes'])
      queryClient.invalidateQueries(['allQuotes'])
      queryClient.invalidateQueries(['quoteStats'])
      if (response.data.success) {
        alert(`BC Quote created successfully! Quote #${response.data.bc_quote_number}`)
      } else {
        alert(`Error creating BC quote: ${response.data.error}`)
      }
    },
    onError: (error) => {
      alert(`Failed to create BC quote: ${error.response?.data?.detail || error.message}`)
    }
  })

  if (isLoading) {
    return <div className="flex justify-center items-center h-64">
      <div className="text-gray-500">Loading...</div>
    </div>
  }

  if (!quote) {
    return <div className="text-center py-12">
      <p className="text-gray-500">Quote not found</p>
    </div>
  }

  const confidence = quote.confidence_scores?.overall || 0
  const confidencePercent = (confidence * 100).toFixed(0)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <button
          onClick={() => navigate('/reviews')}
          className="mb-4 text-sm text-gray-600 hover:text-gray-900"
        >
          ← Back to Review Queue
        </button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              Quote Request #{quote.id}
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              Status: {quote.status} • Confidence: {confidencePercent}%
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Email Info */}
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Email Information</h2>
          <dl className="space-y-3">
            <div>
              <dt className="text-sm font-medium text-gray-500">From</dt>
              <dd className="mt-1 text-sm text-gray-900">{quote.email_from || 'N/A'}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Subject</dt>
              <dd className="mt-1 text-sm text-gray-900">{quote.email_subject || 'N/A'}</dd>
            </div>
          </dl>
        </div>

        {/* Customer Info */}
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Customer Information</h2>
          <dl className="space-y-3">
            <div>
              <dt className="text-sm font-medium text-gray-500">Company</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {quote.parsed_data?.customer?.company_name || 'Not provided'}
              </dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Contact</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {quote.parsed_data?.customer?.contact_name || 'Not provided'}
              </dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Email</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {quote.parsed_data?.customer?.email || 'Not provided'}
              </dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Phone</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {quote.parsed_data?.customer?.phone || 'Not provided'}
              </dd>
            </div>
          </dl>
        </div>
      </div>

      {/* Doors */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Door Specifications</h2>
        <div className="space-y-4">
          {quote.parsed_data?.doors?.map((door, index) => (
            <div key={index} className="border border-gray-200 rounded-lg p-4">
              <h3 className="font-medium text-gray-900 mb-3">Door #{index + 1}</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Model:</span>
                  <span className="ml-2 text-gray-900">{door.model || 'N/A'}</span>
                </div>
                <div>
                  <span className="text-gray-500">Quantity:</span>
                  <span className="ml-2 text-gray-900">{door.quantity || 'N/A'}</span>
                </div>
                <div>
                  <span className="text-gray-500">Size:</span>
                  <span className="ml-2 text-gray-900">
                    {door.width_ft}'{door.width_in}" x {door.height_ft}'{door.height_in}"
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Color:</span>
                  <span className="ml-2 text-gray-900">{door.color || 'N/A'}</span>
                </div>
                <div>
                  <span className="text-gray-500">Track:</span>
                  <span className="ml-2 text-gray-900">{door.track_type || 'N/A'}"</span>
                </div>
                <div>
                  <span className="text-gray-500">Panels:</span>
                  <span className="ml-2 text-gray-900">{door.panel_config || 'N/A'}</span>
                </div>
                <div>
                  <span className="text-gray-500">Glazing:</span>
                  <span className="ml-2 text-gray-900">{door.glazing || 'N/A'}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Generate Quote Button */}
      {!showQuote && (
        <div className="bg-white shadow rounded-lg p-6">
          <button
            onClick={() => generateQuoteMutation.mutate()}
            disabled={generateQuoteMutation.isPending}
            className="w-full inline-flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
          >
            {generateQuoteMutation.isPending ? 'Generating...' : 'Generate Quote with Pricing'}
          </button>
        </div>
      )}

      {/* Generated Quote */}
      {showQuote && quoteData && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Generated Quote</h2>
          <div className="space-y-4">
            {quoteData.items?.map((item, index) => (
              <div key={index} className="flex justify-between border-b pb-2">
                <div>
                  <p className="font-medium">{item.description}</p>
                  <p className="text-sm text-gray-500">Qty: {item.quantity} x ${item.unit_price}</p>
                </div>
                <p className="font-medium">${item.total_price}</p>
              </div>
            ))}
            <div className="pt-4 space-y-2 border-t-2">
              <div className="flex justify-between text-sm">
                <span>Subtotal:</span>
                <span>${quoteData.subtotal}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span>Tax:</span>
                <span>${quoteData.tax}</span>
              </div>
              <div className="flex justify-between text-lg font-bold">
                <span>Total:</span>
                <span>${quoteData.total}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* BC Quote Status */}
      {quote.bc_quote_id && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <div className="flex items-center">
            <svg className="h-5 w-5 text-green-400 mr-2" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
            <div>
              <p className="text-sm font-medium text-green-800">
                Business Central Quote Created
              </p>
              <p className="text-sm text-green-700 mt-1">
                Quote #{quote.bc_quote_id} - Ready for review in Business Central
              </p>
            </div>
          </div>
        </div>
      )}

      {/* BC Quote Creation for Approved Quotes */}
      {quote.status === 'approved' && !quote.bc_quote_id && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
          <div className="flex items-start">
            <div className="flex-shrink-0">
              <svg className="h-6 w-6 text-blue-400" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3 flex-1">
              <h3 className="text-sm font-medium text-blue-800 mb-2">
                Ready to Create in Business Central
              </h3>
              <p className="text-xs text-blue-700 mb-4">
                This quote has been approved. Create it in Business Central to generate a sales quote that can be sent to the customer.
              </p>
              <button
                onClick={() => {
                  if (confirm('Create this quote in Business Central?')) {
                    createBCQuoteMutation.mutate()
                  }
                }}
                disabled={createBCQuoteMutation.isPending}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
              >
                <svg className="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                {createBCQuoteMutation.isPending ? 'Creating in BC...' : 'Create BC Quote'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Review Actions</h2>
        <div className="space-y-4">
          {/* Email Categorization Feedback */}
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <div className="flex items-start">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-yellow-400" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3 flex-1">
                <h3 className="text-sm font-medium text-yellow-800 mb-2">
                  Help AI Learn: Is this actually a quote request?
                </h3>
                <p className="text-xs text-yellow-700 mb-3">
                  If this email was incorrectly categorized as a quote request, let the AI know so it can improve!
                </p>
                <button
                  onClick={() => {
                    if (confirm('Mark this as NOT a quote request? The AI will learn from your feedback.')) {
                      markNotQuoteMutation.mutate()
                    }
                  }}
                  disabled={markNotQuoteMutation.isPending}
                  className="inline-flex items-center px-3 py-1.5 border border-yellow-300 text-sm font-medium rounded-md text-yellow-700 bg-white hover:bg-yellow-50 disabled:opacity-50"
                >
                  <svg className="mr-1.5 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                  {markNotQuoteMutation.isPending ? 'Saving...' : 'Not a Quote Request'}
                </button>
              </div>
            </div>
          </div>

          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Add notes (optional)..."
            rows={3}
            className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-odc-500 focus:border-odc-500"
          />
          <div className="flex space-x-3">
            <button
              onClick={() => approveMutation.mutate()}
              disabled={approveMutation.isPending}
              className="flex-1 inline-flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-green-600 hover:bg-green-700 disabled:opacity-50"
            >
              {approveMutation.isPending ? 'Approving...' : 'Approve'}
            </button>
            <button
              onClick={() => rejectMutation.mutate()}
              disabled={rejectMutation.isPending}
              className="flex-1 inline-flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-red-600 hover:bg-red-700 disabled:opacity-50"
            >
              {rejectMutation.isPending ? 'Rejecting...' : 'Reject'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default QuoteDetail
