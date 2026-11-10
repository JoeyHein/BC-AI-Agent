import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { quotesApi, emailFeedbackApi } from '../api/client'
import apiClient from '../api/client'
import { useState } from 'react'

function sourceBadge(source) {
  const styles = {
    email: 'bg-blue-100 text-blue-800',
    profile: 'bg-emerald-100 text-emerald-800',
    default: 'bg-gray-100 text-gray-700',
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${styles[source] || styles.default}`}>
      {source || 'default'}
    </span>
  )
}

function displayValue(value) {
  if (value == null || value === '') return '—'
  return String(value)
}

function FieldSources({ sources, deviations, match, status, onConfirmCustomer, confirming, onRelease, releasing }) {
  const doors = sources?.doors || []
  const delivery = sources?.deliveryType
  const rows = []
  if (delivery) {
    rows.push({ label: 'Pickup / delivery', ...delivery })
  }
  doors.forEach((door, index) => {
    Object.entries(door || {}).forEach(([field, info]) => {
      if (!info) return
      rows.push({ label: `Door ${index + 1} ${field}`, ...info })
    })
  })
  const deviationList = (deviations || []).filter((item) => item.kind === 'deviation_from_customer_standard' || item.kind === 'locked_rule')
  const otherDeviations = (deviations || []).filter((item) => item.kind !== 'deviation_from_customer_standard' && item.kind !== 'locked_rule')
  const heldMatch = status === 'held_for_customer_match'
  const heldStandard = status === 'held_for_standard_deviation'
  const suggested = !!(match?.suggested && match?.bc_customer_id)
  if (!rows.length && !(deviations || []).length && !match && !heldMatch && !heldStandard) return null
  return (
    <div className="bg-white shadow rounded-lg p-6 space-y-4" data-testid="quote-field-sources">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-medium text-gray-900">How this quote was filled in</h2>
        {sources?.mode && (
          <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Mode {sources.mode}
          </span>
        )}
      </div>
      {sources?.mode === 'shadow' && (
        <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-md p-3">
          Shadow mode. These sources were calculated and stored. The quote sent to Business Central still used the previous defaults.
        </p>
      )}
      {heldStandard && (
        <div className="text-sm text-red-900 bg-red-50 border border-red-300 rounded-md p-4 space-y-2">
          <p className="font-semibold">Held for review. This email differs from the customer standard, so it was not sent to Business Central.</p>
          {deviationList.map((item, index) => (
            <p key={index}>{item.reason}</p>
          ))}
          <button
            type="button"
            onClick={onRelease}
            disabled={releasing}
            className="inline-flex items-center px-3 py-1.5 rounded-md text-sm font-medium text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
          >
            {releasing ? 'Pricing…' : 'Release and price with email values'}
          </button>
        </div>
      )}
      {heldMatch && (
        <div className="text-sm text-red-900 bg-red-50 border border-red-300 rounded-md p-4 space-y-3">
          <p className="font-semibold">
            {suggested ? 'Suggested customer. Confirm before this quote is priced.' : 'Held for customer match.'}
          </p>
          <p>{match?.reason || 'No confident customer, so this was not priced at retail.'}</p>
          {suggested && (
            <button
              type="button"
              onClick={onConfirmCustomer}
              disabled={confirming}
              className="inline-flex items-center px-3 py-1.5 rounded-md text-sm font-medium text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
            >
              {confirming ? 'Saving…' : `Confirm ${match.bc_customer_id}, remember this email, and price`}
            </button>
          )}
        </div>
      )}
      {match && !heldMatch && !heldStandard && (
        <p className="text-sm text-gray-600">
          Customer match: {match.method}. {match.reason}
        </p>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500">
                <th className="py-2 pr-4 font-medium">Field</th>
                <th className="py-2 pr-4 font-medium">Email says</th>
                <th className="py-2 pr-4 font-medium">Profile says</th>
                <th className="py-2 pr-4 font-medium">Used</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label} className="border-t border-gray-100">
                  <td className="py-2 pr-4 text-gray-900">
                    {row.label}
                    {row.marked ? <span className="ml-2 text-xs text-amber-700">marked</span> : null}
                  </td>
                  <td className="py-2 pr-4 text-gray-900">
                    {displayValue(row.email_says)}
                    {row.email_confidence != null && row.email_basis && row.email_basis !== 'silent'
                      ? <span className="ml-1 text-xs text-gray-500">{Math.round(row.email_confidence * 100)}%</span>
                      : null}
                  </td>
                  <td className="py-2 pr-4 text-gray-700">
                    {displayValue(row.profile_says)}
                    {row.profile_locked || row.locked ? ' · locked' : ''}
                    {row.profile_evidence || row.evidence ? <div className="text-xs text-gray-500">{row.profile_evidence || row.evidence}</div> : null}
                  </td>
                  <td className="py-2 pr-4">
                    <span className="mr-2">{displayValue(row.used ?? row.value)}</span>
                    {sourceBadge(row.source)}
                    {row.note ? <div className="text-xs text-amber-800 mt-1">{row.note}</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {deviationList.length > 0 && !heldStandard && (
        <div className="text-sm text-orange-950 bg-orange-50 border border-orange-300 rounded-md p-4 space-y-2">
          <p className="font-semibold">Deviation from customer standard</p>
          {deviationList.map((item, index) => (
            <p key={index}>{item.reason}</p>
          ))}
        </div>
      )}
      {otherDeviations.length > 0 && (
        <ul className="space-y-2">
          {otherDeviations.map((item, index) => (
            <li key={index} className="text-sm text-gray-800 bg-orange-50 border border-orange-200 rounded-md p-3">
              <span className="font-medium">{item.field}</span>
              {item.kind ? ` · ${item.kind}` : ''}
              <div className="mt-1">{item.reason}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Openings({ quote }) {
  const read = quote.parsed_data?.attachments_read
  if (!read) return null
  const openings = read.openings || []
  return (
    <div className="bg-white shadow rounded-lg p-6" data-testid="quote-openings">
      <h2 className="text-lg font-medium text-gray-900">Openings from attachments</h2>
      <p className="mt-1 text-sm text-gray-600">
        {read.opening_count ?? openings.length} opening{(read.opening_count ?? openings.length) === 1 ? '' : 's'} found.
        {read.applied ? ' These counted as what the email said.' : ' Shadow only: they were not used on the quote.'}
      </p>
      <ul className="mt-3 space-y-2">
        {(read.files || []).map((file) => (
          <li key={file.name} className="text-sm text-gray-800">
            <span className="font-medium">{file.name}</span>
            {(file.pages || []).map((page) => (
              <span key={page.page} className="ml-2 text-gray-500">page {page.page} · {page.method === 'ocr_unavailable' || page.method === 'no_text_layer' ? 'no text layer' : page.method}</span>
            ))}
          </li>
        ))}
        {openings.map((opening) => (
          <li key={`${opening.file}-${opening.page}-${opening.index}`} className="text-sm text-gray-900 border border-gray-100 rounded-md p-3">
            Opening {opening.index}: {opening.label}
            <div className="text-xs text-gray-500">{opening.file} · page {opening.page}</div>
          </li>
        ))}
        {openings.length === 0 && <li className="text-sm text-gray-500">No opening size was read. Check the file above.</li>}
      </ul>
    </div>
  )
}

function CustomerApproval({ quote, onChanged }) {
  const approval = quote.customer_approval
  const [choice, setChoice] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  if (!approval || approval.status === 'dismissed') return null
  const candidates = approval.candidates || []
  async function convert() {
    const chosen = approval.status === 'needs_choice' ? choice : approval.bc_quote_number
    if (!chosen) return
    if (!window.confirm(`Convert ${chosen} to a sales order? This is not undone from here.`)) return
    setBusy(true)
    setMessage('')
    try {
      const response = await quotesApi.convertCustomerApproval(approval.id, chosen)
      setMessage(response.data.bc_order_number ? `Sales order ${response.data.bc_order_number}` : 'Converted')
      onChanged()
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Could not convert')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="bg-white shadow rounded-lg p-6 space-y-3" data-testid="customer-approval">
      <h2 className="text-lg font-medium text-gray-900">Convert to sales order</h2>
      <p className="text-sm text-gray-600">
        {approval.status === 'converted'
          ? `Already converted to ${approval.bc_order_number}.`
          : approval.status === 'needs_choice'
            ? 'More than one quote matches. Pick one. Nothing converts until you click.'
            : `Matched ${approval.bc_quote_number}. Nothing converts until you click.`}
      </p>
      {approval.customer_po && (
        <p className="text-sm text-gray-800">Customer PO {approval.customer_po} ({approval.po_source})</p>
      )}
      {approval.status === 'needs_choice' && (
        <select aria-label="Quote to convert" value={choice} onChange={(event) => setChoice(event.target.value)} className="border border-gray-300 rounded-md px-2 py-1 text-sm">
          <option value="">Choose a quote</option>
          {candidates.map((item) => (
            <option key={item.bc_quote_number} value={item.bc_quote_number}>
              {item.bc_quote_number}{item.customer_name ? ` · ${item.customer_name}` : ''}
            </option>
          ))}
        </select>
      )}
      {approval.status !== 'converted' && (
        <button type="button" onClick={convert} disabled={busy || (approval.status === 'needs_choice' && !choice)} className="inline-flex items-center px-3 py-1.5 rounded-md text-sm font-medium text-white bg-odc-600 disabled:opacity-50">
          {busy ? 'Converting…' : 'Convert to SO'}
        </button>
      )}
      {message && <p className="text-sm text-gray-700">{message}</p>}
    </div>
  )
}

function QuoteDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [notes, setNotes] = useState('')
  const [showQuote, setShowQuote] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [releasing, setReleasing] = useState(false)

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

      <Openings quote={quote} />
      <CustomerApproval quote={quote} onChanged={() => queryClient.invalidateQueries({ queryKey: ['quote', id] })} />

      <FieldSources
        sources={quote.field_sources}
        deviations={quote.deviations}
        match={quote.customer_match}
        status={quote.status}
        confirming={confirming}
        releasing={releasing}
        onConfirmCustomer={async () => {
          setConfirming(true)
          try {
            await apiClient.post(`/api/quotes/${quote.id}/confirm-customer`)
            queryClient.invalidateQueries({ queryKey: ['quote', id] })
          } catch (err) {
            alert(err.response?.data?.detail || 'Could not confirm the customer')
          } finally {
            setConfirming(false)
          }
        }}
        onRelease={async () => {
          setReleasing(true)
          try {
            await apiClient.post(`/api/quotes/${quote.id}/release`)
            queryClient.invalidateQueries({ queryKey: ['quote', id] })
          } catch (err) {
            alert(err.response?.data?.detail || 'Could not price the quote')
          } finally {
            setReleasing(false)
          }
        }}
      />

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
