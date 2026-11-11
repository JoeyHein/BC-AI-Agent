export function apiErrorMessage(detail, fallback) {
  if (Array.isArray(detail)) {
    const first = detail[0]
    if (first && typeof first === 'object') {
      return first.msg || first.message || fallback
    }
    if (typeof first === 'string' && first) return first
    return fallback
  }
  if (detail && typeof detail === 'object') {
    return detail.message || detail.msg || fallback
  }
  if (typeof detail === 'string' && detail) return detail
  return fallback
}
