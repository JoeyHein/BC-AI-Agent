/**
 * Door dimension validation — mirrors backend collect_dimension_validation.
 *
 * Allowed lists come from series.specs on /api/door-config/full-config
 * (DOOR_SERIES in door_configurator.py). Craft is stocked only at
 * 8'/9'/12'/16' wide × 7'/8' tall; do not invent extra sizes here.
 *
 * Keep message text in lockstep with backend/app/api/door_configurator.py
 * (format_ft_in / format_ft_in_list / collect_dimension_validation).
 *
 * `strict: true` (default, customer portals): catalog max / stocked lists
 * are hard errors. `strict: false` (staff Door Configurator): those become
 * warnings so custom/oversize quotes can proceed. Absolute envelope still
 * errors in both modes.
 */

/** Absolute staff/calculator envelope — matches backend ABSOLUTE_*_IN. */
export const STAFF_MIN_WIDTH_IN = 60   // 5'
export const STAFF_MAX_WIDTH_IN = 576  // 48'
export const STAFF_MIN_HEIGHT_IN = 60  // 5'
export const STAFF_MAX_HEIGHT_IN = 480 // 40'

export function formatFtIn(totalInches) {
  const inches = Number(totalInches) || 0
  const feet = Math.floor(inches / 12)
  const rem = inches % 12
  return `${feet}'${rem}"`
}

export function formatFtInList(values) {
  const formatted = (values || []).map(formatFtIn)
  if (formatted.length === 0) return ''
  if (formatted.length === 1) return formatted[0]
  if (formatted.length === 2) return `${formatted[0]} and ${formatted[1]}`
  return `${formatted.slice(0, -1).join(', ')}, and ${formatted[formatted.length - 1]}`
}

export function lookupSeries(config, door) {
  if (!config?.doorSeries || !door?.doorType || !door?.doorSeries) return null
  return config.doorSeries[door.doorType]?.find((s) => s.id === door.doorSeries) || null
}

function pushConstraint(bucket, errors, warnings, message) {
  if (bucket === 'error') errors.push(message)
  else warnings.push(message)
}

/**
 * @param {object|null} series
 * @param {number} width
 * @param {number} height
 * @param {{ strict?: boolean }} [options] strict defaults true (customer). Staff pass { strict: false }.
 * @returns {{ errors: string[], warnings: string[], widthInvalid: boolean, heightInvalid: boolean }}
 */
export function getDimensionValidation(series, width, height, options = {}) {
  const strict = options.strict !== false
  const errors = []
  const warnings = []
  let widthInvalid = false
  let heightInvalid = false
  const specs = series?.specs || {}
  const name = series?.name || series?.id || 'This series'
  const w = Number(width) || 0
  const h = Number(height) || 0
  const catalogBucket = strict ? 'error' : 'warning'

  const availableWidths = specs.availableWidths
  if (availableWidths?.length && !availableWidths.includes(w)) {
    pushConstraint(
      catalogBucket,
      errors,
      warnings,
      `${name} is not available in width ${formatFtIn(w)}. Available widths: ${formatFtInList(availableWidths)}.`
    )
    widthInvalid = true
  } else if (specs.maxWidth && w > specs.maxWidth) {
    pushConstraint(
      catalogBucket,
      errors,
      warnings,
      `Door width ${w}" exceeds maximum ${specs.maxWidth}" for ${name}`
    )
    widthInvalid = true
  }

  const availableHeights = specs.availableHeights
  if (availableHeights?.length && !availableHeights.includes(h)) {
    pushConstraint(
      catalogBucket,
      errors,
      warnings,
      `${name} is not available in height ${formatFtIn(h)}. Available heights: ${formatFtInList(availableHeights)}.`
    )
    heightInvalid = true
  } else if (specs.maxHeight && h > specs.maxHeight) {
    pushConstraint(
      catalogBucket,
      errors,
      warnings,
      `Door height ${h}" exceeds maximum ${specs.maxHeight}" for ${name}`
    )
    heightInvalid = true
  }

  if (w && (w < STAFF_MIN_WIDTH_IN || w > STAFF_MAX_WIDTH_IN)) {
    errors.push(
      `Door width must be between ${STAFF_MIN_WIDTH_IN}" and ${STAFF_MAX_WIDTH_IN}" (5' to 48')`
    )
    widthInvalid = true
  }
  if (h && (h < STAFF_MIN_HEIGHT_IN || h > STAFF_MAX_HEIGHT_IN)) {
    errors.push(
      `Door height must be between ${STAFF_MIN_HEIGHT_IN}" and ${STAFF_MAX_HEIGHT_IN}" (5' to 40')`
    )
    heightInvalid = true
  }

  return { errors, warnings, widthInvalid, heightInvalid }
}

export function collectDoorsDimensionValidation(doors, config, options = {}) {
  const errors = []
  const warnings = []
  const list = doors || []
  for (let i = 0; i < list.length; i++) {
    const door = list[i]
    const series = lookupSeries(config, door)
    const result = getDimensionValidation(series, door?.doorWidth, door?.doorHeight, options)
    const prefix = list.length > 1 ? `Door ${i + 1}: ` : ''
    for (const msg of result.errors) errors.push(`${prefix}${msg}`)
    for (const msg of result.warnings) warnings.push(`${prefix}${msg}`)
  }
  return { errors, warnings }
}

export function collectDoorsDimensionErrors(doors, config, options = {}) {
  return collectDoorsDimensionValidation(doors, config, options).errors
}
