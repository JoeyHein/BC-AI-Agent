import { useState } from 'react'

/**
 * QuotePricingDisplay - Shows pricing breakdown for a BC quote
 *
 * Props:
 *   pricing: { subtotal, tax, total, currency }
 *   linePricing: [{ line_type, part_number, description, quantity, unit_price, line_total }]
 *   linesFailed: [{ part_number, description, error, fallback }] | null
 *   bcQuoteNumber: string
 *   doorResults: [{ door_index, door_description, parts_count, success, error }]
 *   compact: boolean - if true, show condensed version (for list pages)
 */
function QuotePricingDisplay({ pricing, linePricing, linesFailed, bcQuoteNumber, doorResults, compact = false }) {
  const [expanded, setExpanded] = useState(!compact)

  if (!pricing) {
    return null
  }

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-CA', {
      style: 'currency',
      currency: pricing.currency || 'CAD',
    }).format(amount || 0)
  }

  // Group line items by door (comments act as delimiters)
  const doorSections = []
  let currentDoor = null

  if (linePricing) {
    for (const line of linePricing) {
      if (line.line_type === 'Comment') {
        if (currentDoor) {
          doorSections.push(currentDoor)
        }
        currentDoor = {
          description: line.description,
          items: [],
          subtotal: 0,
        }
      } else if (currentDoor) {
        currentDoor.items.push(line)
        currentDoor.subtotal += line.line_total || 0
      }
    }
    if (currentDoor) {
      doorSections.push(currentDoor)
    }
  }

  // Compact view - just totals
  if (compact && !expanded) {
    return (
      <div className="bg-green-50 border border-green-200 rounded-lg p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <DollarIcon className="h-5 w-5 text-green-600" />
            <div>
              <span className="text-sm font-medium text-green-800">
                {formatCurrency(pricing.total)}
              </span>
              {bcQuoteNumber && (
                <span className="ml-2 text-xs text-green-600">
                  Quote #{bcQuoteNumber}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={() => setExpanded(true)}
            className="text-xs text-green-700 hover:text-green-900 underline"
          >
            View details
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <DollarIcon className="h-5 w-5 text-gray-600" />
            <h3 className="text-sm font-medium text-gray-900">Quote Pricing</h3>
            {bcQuoteNumber && (
              <span className="text-xs text-gray-500">
                BC Quote #{bcQuoteNumber}
              </span>
            )}
          </div>
          {compact && (
            <button
              onClick={() => setExpanded(false)}
              className="text-xs text-gray-500 hover:text-gray-700"
            >
              Collapse
            </button>
          )}
        </div>
      </div>

      {/* Door Sections - package price only (no line-item detail) */}
      {doorSections.length > 0 && (
        <div className="divide-y divide-gray-100">
          {doorSections.map((door, doorIdx) => (
            <div key={doorIdx} className="px-4 py-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-medium text-odc-700">
                    {door.description}
                  </h4>
                  <span className="text-xs text-gray-500">
                    {door.items.length} item{door.items.length !== 1 ? 's' : ''}
                  </span>
                </div>
                <span className="text-sm font-medium text-gray-700">
                  {formatCurrency(door.subtotal)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Failed items warning */}
      {linesFailed && linesFailed.length > 0 && (
        <div className="px-4 py-3 bg-yellow-50 border-t border-yellow-200">
          <div className="flex items-start space-x-2">
            <WarningIcon className="h-4 w-4 text-yellow-600 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-xs font-medium text-yellow-800">
                {linesFailed.length} item{linesFailed.length > 1 ? 's' : ''} could not be priced
              </p>
              <ul className="mt-1 text-xs text-yellow-700 space-y-0.5">
                {linesFailed.map((item, idx) => (
                  <li key={idx}>
                    {item.part_number}
                    {item.description && ` - ${item.description}`}
                    {item.fallback === 'comment' && ' (added as note)'}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Totals */}
      <div className="px-4 py-3 bg-gray-50 border-t border-gray-200">
        <div className="space-y-1">
          <div className="flex justify-between text-sm text-gray-600">
            <span>Subtotal</span>
            <span>{formatCurrency(pricing.subtotal)}</span>
          </div>
          <div className="flex justify-between text-sm text-gray-600">
            <span>Tax</span>
            <span>{formatCurrency(pricing.tax)}</span>
          </div>
          <div className="flex justify-between text-base font-semibold text-gray-900 pt-1 border-t border-gray-300">
            <span>Total</span>
            <span>{formatCurrency(pricing.total)}</span>
          </div>
        </div>
      </div>

      {/* Door generation results (if any had errors) */}
      {doorResults && doorResults.some(d => !d.success) && (
        <div className="px-4 py-2 bg-red-50 border-t border-red-200">
          <p className="text-xs text-red-700">
            Some doors had issues generating parts:
          </p>
          {doorResults.filter(d => !d.success).map((d, idx) => (
            <p key={idx} className="text-xs text-red-600 mt-0.5">
              Door {d.door_index}: {d.error}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function DollarIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

function WarningIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
    </svg>
  )
}

export default QuotePricingDisplay
