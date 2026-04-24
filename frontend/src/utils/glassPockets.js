// Glass pocket (center stile) customization for AL976 and SWD aluminum doors.
// Shared between admin DoorConfigurator and customer QuoteBuilder so both
// enforce the same constraints and storage format. The widget has its own
// copy at widget/src/utils/glassPockets.js (separate build tree).
//
// Storage format on door config: glassPocketsPerSection = {0: n, 1: n, ...}
// or null when every section matches the width-based default.

export const GLASS_POCKET_SERIES = ['AL976', 'SWD']

export function hasGlassPockets(doorSeries) {
  return GLASS_POCKET_SERIES.includes(doorSeries)
}

// Default pocket count based on door width in inches. Matches
// backend _default_glass_pockets() exactly — keep these in sync.
export function defaultPocketsForWidth(widthInches) {
  const f = (widthInches || 96) / 12
  if (f <= 10) return 3
  if (f <= 14) return 4
  if (f <= 18) return 5
  if (f <= 22) return 6
  return 7
}

// Aluminum sections are 21" tall; door height determines how many.
export function sectionCountForHeight(heightInches) {
  return Math.round((heightInches || 84) / 21) || 4
}

// Per-series adjust range.
// - AL976: +3 / -1 from default
// - SWD:   +3 / down to 1 (any within range)
export function pocketConstraints(doorSeries, widthInches) {
  const defaultCount = defaultPocketsForWidth(widthInches)
  const isSWD = doorSeries === 'SWD'
  const maxAdjust = 3
  const minAdjust = isSWD ? defaultCount : 1
  return {
    default: defaultCount,
    min: Math.max(1, defaultCount - minAdjust),
    max: defaultCount + maxAdjust,
  }
}

// Read the current count from a pockets object, falling back to default.
export function getCurrentPocketCount(pockets, defaultCount) {
  if (!pockets || typeof pockets !== 'object') return defaultCount
  const first = pockets[0]
  return first != null ? first : defaultCount
}

// Build the storage value for a given count. Returns null when the count
// matches the default (so we don't persist unnecessary overrides).
export function buildPocketsForCount(count, sectionCount, defaultCount) {
  if (count === defaultCount) return null
  const obj = {}
  for (let i = 0; i < sectionCount; i++) obj[i] = count
  return obj
}
