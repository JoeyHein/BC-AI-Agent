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
  const [expandedDoors, setExpandedDoors] = useState(new Set())

  if (!pricing) {
    return null
  }

  const isEstimate = pricing.is_estimate === true

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
        // Only door description comments start a new group;
        // "Note" lines (e.g. window placement) stay in the current group.
        if (currentDoor) {
          doorSections.push(currentDoor)
        }
        currentDoor = {
          description: line.description,
          items: [],
          subtotal: 0,
        }
      } else if (line.line_type === 'Note' && currentDoor) {
        // Window/note comments — show inline as a note, don't split the group
        currentDoor.items.push(line)
      } else if (currentDoor) {
        currentDoor.items.push(line)
        currentDoor.subtotal += line.line_total || 0
      }
    }
    if (currentDoor) {
      doorSections.push(currentDoor)
    }
  }

  const toggleDoor = (idx) => {
    setExpandedDoors(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  // Compact view - just totals
  if (compact && !expanded) {
    return (
      <div className={`border rounded-lg p-3 ${isEstimate ? 'bg-amber-50 border-amber-200' : 'bg-green-50 border-green-200'}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <DollarIcon className={`h-5 w-5 ${isEstimate ? 'text-amber-600' : 'text-green-600'}`} />
            <div>
              <span className={`text-sm font-medium ${isEstimate ? 'text-amber-800' : 'text-green-800'}`}>
                {formatCurrency(pricing.total)}
              </span>
              {isEstimate ? (
                <span className="ml-2 text-xs text-amber-600">Estimate — retail rates, excl. tax</span>
              ) : bcQuoteNumber ? (
                <span className="ml-2 text-xs text-green-600">Quote #{bcQuoteNumber}</span>
              ) : null}
            </div>
          </div>
          <button
            onClick={() => setExpanded(true)}
            className={`text-xs underline ${isEstimate ? 'text-amber-700 hover:text-amber-900' : 'text-green-700 hover:text-green-900'}`}
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
            {isEstimate ? (
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800">
                Estimate — retail rates, excl. tax
              </span>
            ) : bcQuoteNumber ? (
              <span className="text-xs text-gray-500">BC Quote #{bcQuoteNumber}</span>
            ) : null}
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
        {isEstimate && (
          <p className="mt-1 text-xs text-amber-700">
            Your account is not yet linked to a Business Central record. Pricing shown is an estimate at standard retail rates and excludes tax. Contact us to complete your account setup.
          </p>
        )}
      </div>

      {/* Door Sections - subtotaled pricing with expandable line items */}
      {doorSections.length > 0 && (
        <div className="divide-y divide-gray-100">
          {doorSections.map((door, doorIdx) => {
            const isOpen = expandedDoors.has(doorIdx)
            return (
              <div key={doorIdx}>
                <button
                  type="button"
                  onClick={() => toggleDoor(doorIdx)}
                  className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center space-x-2">
                    <ChevronIcon className="h-4 w-4 text-gray-400 flex-shrink-0" expanded={isOpen} />
                    <div className="text-left">
                      <h4 className="text-sm font-medium text-odc-700">
                        {door.description}
                      </h4>
                      <span className="text-xs text-gray-500">
                        {door.items.filter(i => i.line_type !== 'Note').length} item{door.items.filter(i => i.line_type !== 'Note').length !== 1 ? 's' : ''}
                      </span>
                    </div>
                  </div>
                  <span className="text-sm font-medium text-gray-700">
                    {formatCurrency(door.subtotal)}
                  </span>
                </button>
                {isOpen && door.items.length > 0 && (
                  <div className="px-4 pb-3">
                    <table className="w-full ml-6">
                      <tbody className="text-xs text-gray-600">
                        {door.items.map((item, itemIdx) => (
                          <tr key={itemIdx}>
                            <td className={`py-0.5 pr-4 ${item.line_type === 'Note' ? 'font-medium text-gray-700 pt-2' : ''}`}>
                              {item.description}
                            </td>
                            <td className="py-0.5 text-right whitespace-nowrap text-gray-500">
                              {item.line_type !== 'Note' && `qty ${item.quantity}`}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Pricing warnings are logged server-side for admin visibility only */}

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
        <p className="mt-2 text-xs text-gray-400 italic">
          Freight is estimated. Actual shipping costs may vary based on order volume and destination.
        </p>
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

function ChevronIcon({ className, expanded }) {
  return (
    <svg
      className={`${className} transition-transform ${expanded ? 'rotate-90' : ''}`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
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
