import { useState } from 'react'

/**
 * Customer quote pricing.
 *
 * A door package is one row: the description, the door quantity, and the
 * package total. Component lines, unit prices, and internal notes are not
 * rendered. A part that is not inside a package (and freight) stays its own
 * row. Staff quotes do not use this component.
 */
const DOOR_QTY = /^\(\s*(\d+)\s*\)/
const HOIST_PARTS = new Set(['SP12-00084-00', 'FH12-00190-00'])

function freightWasWaived(freight) {
  if (!freight || !freight.skip) return false
  return !String(freight.description || '').toLowerCase().startsWith('pickup')
}

function isFreightItem(line) {
  return line?.line_type === 'Freight' || (line?.part_number || '').toUpperCase() === 'FREIGHT'
}

function isFreightNote(line) {
  return (line?.description || '').toLowerCase().startsWith('freight is an estimate')
}

function isDoorHeader(line) {
  return line?.line_type === 'Comment' && DOOR_QTY.test((line.description || '').trim())
}

function isHiddenNote(line) {
  if (!line || isFreightItem(line)) return false
  if (line.line_type === 'Note' || line.line_type === 'freight_note') return true
  if (isFreightNote(line)) return true
  if (/^price note\b/i.test((line.description || '').trim())) return true
  return line.line_type === 'Comment' && !isDoorHeader(line)
}

function isOperatorLine(line) {
  const part = (line?.part_number || '').toUpperCase()
  if (part.startsWith('OP') || HOIST_PARTS.has(part)) return true
  const description = line?.description || ''
  if (/male rail|female rail|end rail|build-?up rail/i.test(description)) return false
  return /\brails?\b/i.test(description) && /\d+\s*(?:ft\.?|foot|')/i.test(description)
}

function doorQuantity(description) {
  const match = DOOR_QTY.exec((description || '').trim())
  return match ? Number(match[1]) : 1
}

function amount(line) {
  const value = Number(line?.line_total)
  return Number.isFinite(value) ? value : 0
}

/**
 * Prefer rows the API already collapsed. A full component payload is rolled
 * up here as well, so a stale response cannot paint unit prices.
 */
function customerRows(linePricing) {
  const rows = []
  const freightLines = []
  if (!linePricing?.length) return { rows, freightLines }

  const alreadyCollapsed = linePricing.some(
    (line) => line?.line_type === 'Package' || line?.line_type === 'Freight',
  )
  if (alreadyCollapsed) {
    for (const line of linePricing) {
      if (isHiddenNote(line)) continue
      if (isFreightItem(line)) {
        freightLines.push({
          ...line,
          description: 'Freight (estimate)',
          quantity: 1,
          line_total: line.line_total ?? line.unit_price,
        })
        continue
      }
      if (line.line_type === 'Package' || line.line_type === 'Item') {
        rows.push(line)
      }
    }
    return { rows, freightLines }
  }

  let packageRow = null
  let buffered = []
  const flush = () => {
    if (packageRow) {
      rows.push(packageRow)
      packageRow = null
    }
    rows.push(...buffered)
    buffered = []
  }

  for (const line of linePricing) {
    if (isFreightNote(line) || isHiddenNote(line)) continue
    if (isFreightItem(line)) {
      flush()
      freightLines.push(line)
      continue
    }
    if (isDoorHeader(line)) {
      flush()
      packageRow = {
        line_type: 'Package',
        description: line.description,
        quantity: doorQuantity(line.description),
        line_total: 0,
      }
      continue
    }
    if (isOperatorLine(line) || line.part_number === 'INSTALLATION') {
      const item = {
        line_type: 'Item',
        description: line.description,
        quantity: line.quantity,
        line_total: amount(line),
      }
      if (packageRow) buffered.push(item)
      else rows.push(item)
      continue
    }
    if (packageRow && line.line_type === 'Item') {
      packageRow.line_total += amount(line)
      continue
    }
    if (line.line_type === 'Item') {
      rows.push({
        line_type: 'Item',
        description: line.description,
        quantity: line.quantity,
        line_total: amount(line),
      })
    }
  }
  flush()
  return { rows, freightLines }
}

function QuotePricingDisplay({ pricing, linePricing, bcQuoteNumber, doorResults, freight, compact = false }) {
  const [expanded, setExpanded] = useState(!compact)

  if (!pricing) {
    return null
  }

  const isEstimate = pricing.is_estimate === true
  const { rows, freightLines } = customerRows(linePricing)
  const waived = freightWasWaived(freight) && freightLines.length === 0

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-CA', {
      style: 'currency',
      currency: pricing.currency || 'CAD',
    }).format(value || 0)
  }

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

      {rows.length > 0 && (
        <div className="divide-y divide-gray-100">
          <div className="px-4 py-2 flex items-center justify-between text-xs font-medium uppercase tracking-wide text-gray-400">
            <span>Description</span>
            <span className="flex gap-6">
              <span className="w-16 text-right">Qty</span>
              <span className="w-24 text-right">Total</span>
            </span>
          </div>
          {rows.map((row, index) => (
            <div key={index} className="px-4 py-3 flex items-start justify-between gap-4">
              <h4 className="text-sm font-medium text-odc-700">{row.description}</h4>
              <div className="flex flex-shrink-0 items-start gap-6">
                <span className="w-16 text-right text-sm text-gray-600">{row.quantity}</span>
                <span className="w-24 text-right text-sm font-medium text-gray-900">
                  {formatCurrency(row.line_total)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {freightLines.length > 0 && (
        <div className="px-4 py-3 border-t border-gray-200">
          {freightLines.map((line, index) => (
            <div key={index} className="flex justify-between text-sm text-gray-800">
              <span>Freight (estimate)</span>
              <span>{formatCurrency(line.line_total || line.unit_price)}</span>
            </div>
          ))}
          <p className="mt-1 text-xs text-gray-400 italic">
            Freight is an estimate. If the actual shipping cost comes in higher, the difference will be added to the invoice.
          </p>
        </div>
      )}

      {waived && (
        <div className="px-4 py-3 border-t border-gray-200">
          <div className="flex justify-between text-sm text-gray-800">
            <span>Freight</span>
            <span>{formatCurrency(0)}</span>
          </div>
          <p className="mt-1 text-xs text-gray-500">Freight is waived for this customer.</p>
        </div>
      )}

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
        {freightLines.length === 0 && !waived && (
          <p className="mt-2 text-xs text-gray-400 italic">
            Freight is an estimate. If the actual shipping cost comes in higher, the difference will be added to the invoice.
          </p>
        )}
      </div>

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

export default QuotePricingDisplay
