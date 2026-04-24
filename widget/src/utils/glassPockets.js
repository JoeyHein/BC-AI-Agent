// Glass pocket (center stile) customization for AL976 and SWD aluminum doors.
// Mirrors frontend/src/utils/glassPockets.js — widget is a separate build so
// the file is duplicated rather than imported across build trees. Keep these
// two files in sync.

export const GLASS_POCKET_SERIES = ['AL976', 'SWD']

export function hasGlassPockets(doorSeries) {
  return GLASS_POCKET_SERIES.includes(doorSeries)
}

export function defaultPocketsForWidth(widthInches) {
  const f = (widthInches || 96) / 12
  if (f <= 10) return 3
  if (f <= 14) return 4
  if (f <= 18) return 5
  if (f <= 22) return 6
  return 7
}

export function sectionCountForHeight(heightInches) {
  return Math.round((heightInches || 84) / 21) || 4
}

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

export function getCurrentPocketCount(pockets, defaultCount) {
  if (!pockets || typeof pockets !== 'object') return defaultCount
  const first = pockets[0]
  return first != null ? first : defaultCount
}

export function buildPocketsForCount(count, sectionCount, defaultCount) {
  if (count === defaultCount) return null
  const obj = {}
  for (let i = 0; i < sectionCount; i++) obj[i] = count
  return obj
}
