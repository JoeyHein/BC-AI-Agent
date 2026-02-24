import { useQuery } from '@tanstack/react-query'
import { quotesApi } from '../api/client'
import { Link } from 'react-router-dom'

function ReviewQueue() {
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
