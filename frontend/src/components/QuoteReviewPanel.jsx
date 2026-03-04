import { useState } from 'react'
import { quoteReviewApi } from '../api/client'

/**
 * QuoteReviewPanel — shows diff between original configurator output and current BC quote.
 * Displays added/removed/modified parts in color-coded sections with optional AI analysis.
 */
export default function QuoteReviewPanel({ bcQuoteId, bcQuoteNumber, onClose }) {
  const [loading, setLoading] = useState(false)
  const [reviewData, setReviewData] = useState(null)
  const [error, setError] = useState(null)
  const [includeAI, setIncludeAI] = useState(false)

  const handleReview = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await quoteReviewApi.reviewQuote(bcQuoteId, { include_ai: includeAI })
      setReviewData(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Review failed')
    } finally {
      setLoading(false)
    }
  }

  const diff = reviewData?.diff

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-lg shadow-sm">
      <div className="flex items-center justify-between p-4 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-800">
          Quote Review — {bcQuoteNumber}
        </h3>
        {onClose && (
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-sm">
            Close
          </button>
        )}
      </div>

      {!reviewData && (
        <div className="p-4 space-y-3">
          <p className="text-sm text-gray-600">
            Compare the original configurator output against the current BC quote to detect manual edits.
          </p>
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={includeAI}
              onChange={(e) => setIncludeAI(e.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Include AI analysis (explains changes & suggests fixes)
          </label>
          <button
            onClick={handleReview}
            disabled={loading}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md disabled:opacity-50"
          >
            {loading ? 'Reviewing...' : 'Run Review'}
          </button>
          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}
        </div>
      )}

      {reviewData && diff && (
        <div className="p-4 space-y-4">
          {/* Summary */}
          <div className={`p-3 rounded-md text-sm font-medium ${
            diff.has_changes
              ? 'bg-yellow-50 text-yellow-800 border border-yellow-200'
              : 'bg-green-50 text-green-800 border border-green-200'
          }`}>
            {diff.summary}
          </div>

          {/* Added Parts */}
          {diff.added?.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-green-700 mb-2">
                Added ({diff.added.length})
              </h4>
              <div className="space-y-1">
                {diff.added.map((item, i) => (
                  <div key={i} className="flex items-center justify-between bg-green-50 border border-green-100 rounded px-3 py-2 text-sm">
                    <div>
                      <span className="font-mono font-medium text-green-800">{item.part_number}</span>
                      <span className="text-green-600 ml-2">{item.description}</span>
                    </div>
                    <div className="text-right text-green-700">
                      Qty: {item.quantity}
                      {item.unit_price > 0 && <span className="ml-2">${item.unit_price.toFixed(2)}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Removed Parts */}
          {diff.removed?.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-red-700 mb-2">
                Removed ({diff.removed.length})
              </h4>
              <div className="space-y-1">
                {diff.removed.map((item, i) => (
                  <div key={i} className="flex items-center justify-between bg-red-50 border border-red-100 rounded px-3 py-2 text-sm">
                    <div>
                      <span className="font-mono font-medium text-red-800 line-through">{item.part_number}</span>
                      <span className="text-red-600 ml-2">{item.description}</span>
                    </div>
                    <div className="text-right text-red-700">
                      Qty: {item.quantity}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Modified Parts */}
          {diff.modified?.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-amber-700 mb-2">
                Modified ({diff.modified.length})
              </h4>
              <div className="space-y-1">
                {diff.modified.map((item, i) => (
                  <div key={i} className="bg-amber-50 border border-amber-100 rounded px-3 py-2 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-medium text-amber-800">{item.part_number}</span>
                      <span className="text-amber-600">{item.description}</span>
                    </div>
                    <div className="mt-1 flex gap-4 text-xs text-amber-700">
                      {item.quantity_original !== undefined && (
                        <span>
                          Qty: <span className="line-through">{item.quantity_original}</span> → <span className="font-semibold">{item.quantity_current}</span>
                        </span>
                      )}
                      {item.price_original !== undefined && (
                        <span>
                          Price: <span className="line-through">${item.price_original.toFixed(2)}</span> → <span className="font-semibold">${item.price_current.toFixed(2)}</span>
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Unchanged count */}
          {diff.unchanged_count > 0 && (
            <p className="text-xs text-gray-500">
              {diff.unchanged_count} part(s) unchanged
            </p>
          )}

          {/* AI Analysis */}
          {reviewData.ai_analysis && !reviewData.ai_analysis.error && (
            <div className="border-t border-gray-200 pt-4">
              <h4 className="text-sm font-semibold text-purple-700 mb-3">AI Analysis</h4>

              {reviewData.ai_analysis.summary && (
                <p className="text-sm text-gray-700 mb-3 italic">
                  {reviewData.ai_analysis.summary}
                </p>
              )}

              {reviewData.ai_analysis.changes_analysis?.map((item, i) => (
                <div key={i} className="mb-2 bg-purple-50 border border-purple-100 rounded px-3 py-2 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-purple-800">{item.part_number}</span>
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                      item.severity === 'high' ? 'bg-red-100 text-red-700' :
                      item.severity === 'medium' ? 'bg-amber-100 text-amber-700' :
                      'bg-gray-100 text-gray-600'
                    }`}>
                      {item.severity}
                    </span>
                    {item.is_configurator_issue && (
                      <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                        Configurator Bug
                      </span>
                    )}
                  </div>
                  <p className="text-purple-700 mt-1">{item.likely_reason}</p>
                  {item.suggested_fix && (
                    <p className="text-xs text-purple-600 mt-1">
                      Fix: {item.suggested_fix}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Re-run button */}
          <div className="flex gap-2 pt-2 border-t border-gray-100">
            <button
              onClick={() => { setReviewData(null); setIncludeAI(false) }}
              className="px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded"
            >
              Reset
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
