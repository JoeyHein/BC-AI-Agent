// Timestamp helpers — backend stores naive UTC datetimes (no tz suffix on the
// JSON wire). JavaScript's `new Date(str)` interprets a tz-less ISO string as
// LOCAL time, which displays UTC times as if they were local — off by however
// many hours the user is from UTC. These helpers append `Z` when missing so
// the parse + locale conversion is correct.

function parseUtc(value) {
  if (!value) return null
  if (value instanceof Date) return value
  const s = String(value)
  if (s.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(s)) return new Date(s)
  return new Date(s + 'Z')
}

export function formatDateTime(value, opts) {
  const d = parseUtc(value)
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleString(undefined, opts) : ''
}

export function formatDate(value, opts) {
  const d = parseUtc(value)
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString(undefined, opts) : ''
}

export function formatTime(value, opts) {
  const d = parseUtc(value)
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString(undefined, opts) : ''
}

export { parseUtc }
