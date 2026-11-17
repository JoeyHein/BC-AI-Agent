// Card title for My Quotes. Matches backend/app/services/saved_quote_title.py:
// the job name / tag the customer typed, then the description, then a PO /
// reference, then the SQ number. Never the placeholder "No description".

const TAG_KEYS = ['tagName', 'jobName', 'quoteName', 'tag', 'job_name', 'quote_name']
const REFERENCE_KEYS = ['poNumber', 'po_number', 'reference', 'customerReference']

function clean(value) {
  return String(value ?? '').trim()
}

function first(values) {
  for (const value of values) {
    const text = clean(value)
    if (text) return text
  }
  return ''
}

export function quoteTagName(quote) {
  const config = quote?.config_data || {}
  return first([quote?.name, ...TAG_KEYS.map((key) => config[key])])
}

export function quoteCardTitle(quote) {
  const fromApi = clean(quote?.display_title)
  if (fromApi) return fromApi
  const config = quote?.config_data || {}
  return first([
    quoteTagName(quote),
    quote?.description,
    ...REFERENCE_KEYS.map((key) => config[key]),
    quote?.bc_quote_number,
  ]) || 'Quote'
}

export function quoteCardSubtitle(quote) {
  const description = clean(quote?.description)
  if (!description || description === quoteCardTitle(quote)) return ''
  return description
}
