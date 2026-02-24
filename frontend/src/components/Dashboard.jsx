import { useQuery } from '@tanstack/react-query'
import { quotesApi, emailFeedbackApi } from '../api/client'
import { Link } from 'react-router-dom'

function Dashboard() {
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['learningProgress'],
    queryFn: async () => {
      const response = await quotesApi.getLearningProgress()
      return response.data
    },
  })

  const { data: quotes, isLoading: quotesLoading } = useQuery({
    queryKey: ['allQuotes'],
    queryFn: async () => {
      const response = await quotesApi.getAllQuotes()
      return response.data
    },
  })

  const { data: categorizationStats, isLoading: catStatsLoading } = useQuery({
    queryKey: ['categorizationStats'],
    queryFn: async () => {
      const response = await emailFeedbackApi.getCategorizationStats()
      return response.data
    },
  })

  const { data: quoteStats, isLoading: quoteStatsLoading } = useQuery({
    queryKey: ['quoteStats'],
    queryFn: async () => {
      const response = await quotesApi.getQuoteStats()
      return response.data
    },
  })

  if (statsLoading || quotesLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-gray-500">Loading...</div>
      </div>
    )
  }

  const pendingCount = stats?.pending_reviews || 0
  const totalExamples = stats?.total_examples || 0
  const verifiedExamples = stats?.verified_examples || 0
  const approvalRate = verifiedExamples > 0
    ? ((verifiedExamples / totalExamples) * 100).toFixed(0)
    : 0

  return (
    <div className="space-y-6">
      {/* Stats Cards */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Pending Reviews"
          value={pendingCount}
          subtitle={pendingCount === 1 ? 'quote needs review' : 'quotes need review'}
          color="blue"
        />
        <StatCard
          title="Total Examples"
          value={totalExamples}
          subtitle="in learning library"
          color="green"
        />
        <StatCard
          title="Verified Examples"
          value={verifiedExamples}
          subtitle="high quality parses"
          color="purple"
        />
        <StatCard
          title="Approval Rate"
          value={`${approvalRate}%`}
          subtitle="quotes approved"
          color="indigo"
        />
      </div>

      {/* Categorization Learning Stats */}
      {!catStatsLoading && categorizationStats && categorizationStats.total_verified > 0 && (
        <div className="bg-white shadow rounded-lg">
          <div className="px-4 py-5 sm:px-6 border-b border-gray-200">
            <h3 className="text-lg leading-6 font-medium text-gray-900">
              AI Learning Progress
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Email categorization accuracy improves as you provide feedback
            </p>
          </div>
          <div className="px-4 py-5 sm:p-6">
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
              <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-4 border border-green-200">
                <dt className="text-sm font-medium text-green-900 mb-1">Accuracy Rate</dt>
                <dd className="text-3xl font-bold text-green-700">
                  {(categorizationStats.accuracy_rate * 100).toFixed(1)}%
                </dd>
                <dd className="text-xs text-green-600 mt-1">
                  {categorizationStats.correct_categorizations} of {categorizationStats.total_verified} correct
                </dd>
              </div>
              <div className="bg-gradient-to-br from-yellow-50 to-yellow-100 rounded-lg p-4 border border-yellow-200">
                <dt className="text-sm font-medium text-yellow-900 mb-1">False Positive Rate</dt>
                <dd className="text-3xl font-bold text-yellow-700">
                  {(categorizationStats.false_positive_rate * 100).toFixed(1)}%
                </dd>
                <dd className="text-xs text-yellow-600 mt-1">
                  Emails incorrectly marked as quotes
                </dd>
              </div>
              <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 border border-blue-200">
                <dt className="text-sm font-medium text-blue-900 mb-1">Learning Examples</dt>
                <dd className="text-3xl font-bold text-blue-700">
                  {categorizationStats.learning_examples_available}
                </dd>
                <dd className="text-xs text-blue-600 mt-1">
                  Used to train AI
                </dd>
              </div>
            </div>
            {categorizationStats.total_verified < 10 && (
              <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-4">
                <div className="flex">
                  <div className="flex-shrink-0">
                    <svg className="h-5 w-5 text-blue-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <div className="ml-3 flex-1">
                    <p className="text-sm text-blue-700">
                      <strong>Tip:</strong> Provide feedback on at least 20-30 emails to see significant accuracy improvements.
                      The AI learns from your corrections!
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* BC Quote Integration Stats */}
      {!quoteStatsLoading && quoteStats && (
        <div className="bg-white shadow rounded-lg">
          <div className="px-4 py-5 sm:px-6 border-b border-gray-200">
            <h3 className="text-lg leading-6 font-medium text-gray-900">
              Business Central Quote Integration
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Track quote approval and BC quote creation
            </p>
          </div>
          <div className="px-4 py-5 sm:p-6">
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-4">
              <div className="bg-gradient-to-br from-yellow-50 to-yellow-100 rounded-lg p-4 border border-yellow-200">
                <dt className="text-sm font-medium text-yellow-900 mb-1">Pending Review</dt>
                <dd className="text-3xl font-bold text-yellow-700">
                  {quoteStats.total_pending || 0}
                </dd>
                <dd className="text-xs text-yellow-600 mt-1">
                  Awaiting manager approval
                </dd>
              </div>
              <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-4 border border-green-200">
                <dt className="text-sm font-medium text-green-900 mb-1">Approved</dt>
                <dd className="text-3xl font-bold text-green-700">
                  {quoteStats.total_approved || 0}
                </dd>
                <dd className="text-xs text-green-600 mt-1">
                  Ready for BC creation
                </dd>
              </div>
              <div className="bg-gradient-to-br from-odc-50 to-odc-100 rounded-lg p-4 border border-odc-200">
                <dt className="text-sm font-medium text-odc-900 mb-1">BC Quotes Created</dt>
                <dd className="text-3xl font-bold text-odc-700">
                  {quoteStats.total_bc_created || 0}
                </dd>
                <dd className="text-xs text-odc-600 mt-1">
                  Created in Business Central
                </dd>
              </div>
              <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-lg p-4 border border-purple-200">
                <dt className="text-sm font-medium text-purple-900 mb-1">Approval Rate</dt>
                <dd className="text-3xl font-bold text-purple-700">
                  {quoteStats.approval_rate || 0}%
                </dd>
                <dd className="text-xs text-purple-600 mt-1">
                  Quotes approved
                </dd>
              </div>
            </div>
            {quoteStats.recent_quotes_7d > 0 && (
              <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-4">
                <div className="flex">
                  <div className="flex-shrink-0">
                    <svg className="h-5 w-5 text-blue-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <div className="ml-3 flex-1">
                    <p className="text-sm text-blue-700">
                      <strong>{quoteStats.recent_quotes_7d}</strong> new quote requests in the last 7 days
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Recent Quotes */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:px-6 border-b border-gray-200">
          <h3 className="text-lg leading-6 font-medium text-gray-900">
            Recent Quote Requests
          </h3>
        </div>
        <div className="px-4 py-5 sm:p-6">
          {quotes && quotes.length > 0 ? (
            <div className="space-y-4">
              {quotes.slice(0, 5).map((quote) => (
                <QuoteRow key={quote.id} quote={quote} />
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-center py-8">
              No pending quote requests
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

function StatCard({ title, value, subtitle, color }) {
  const colors = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    purple: 'bg-purple-500',
    indigo: 'bg-odc-500',
  }

  return (
    <div className="bg-white overflow-hidden shadow rounded-lg">
      <div className="p-5">
        <div className="flex items-center">
          <div className="flex-shrink-0">
            <div className={`${colors[color]} rounded-md p-3`}>
              <svg className="h-6 w-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
          </div>
          <div className="ml-5 w-0 flex-1">
            <dl>
              <dt className="text-sm font-medium text-gray-500 truncate">{title}</dt>
              <dd className="flex items-baseline">
                <div className="text-2xl font-semibold text-gray-900">{value}</div>
              </dd>
              <dd className="text-sm text-gray-500">{subtitle}</dd>
            </dl>
          </div>
        </div>
      </div>
    </div>
  )
}

function QuoteRow({ quote }) {
  const confidence = quote.confidence_scores?.overall || 0
  const confidencePercent = (confidence * 100).toFixed(0)

  const getConfidenceColor = (confidence) => {
    if (confidence >= 0.8) return 'text-green-600 bg-green-100'
    if (confidence >= 0.6) return 'text-yellow-600 bg-yellow-100'
    return 'text-red-600 bg-red-100'
  }

  return (
    <Link
      to={`/reviews/${quote.id}`}
      className="block hover:bg-gray-50 transition rounded-lg p-4 border border-gray-200"
    >
      <div className="flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">
            {quote.customer_name || 'Unknown Customer'}
          </p>
          <p className="text-sm text-gray-500 truncate">
            {quote.contact_email || 'No email'}
          </p>
        </div>
        <div className="ml-4 flex-shrink-0 flex items-center space-x-2">
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getConfidenceColor(confidence)}`}>
            {confidencePercent}% confidence
          </span>
          <span className="text-sm text-gray-500">{quote.status}</span>
        </div>
      </div>
    </Link>
  )
}

export default Dashboard
