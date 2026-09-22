/**
 * Door dimension validation — mirrors backend collect_dimension_validation.
 *
 * Allowed lists come from series.specs on /api/door-config/full-config
 * (DOOR_SERIES in door_configurator.py). Craft is stocked only at
 * 8'/9'/12'/16' wide × 7'/8' tall; do not invent extra sizes here.
 *
 * Keep message text in lockstep with backend/app/api/door_configurator.py
 * (format_ft_in / format_ft_in_list / collect_dimension_validation).
 */

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

/**
 * @returns {{ errors: string[], widthInvalid: boolean, heightInvalid: boolean }}
 */
export function getDimensionValidation(series, width, height) {
  const errors = []
  let widthInvalid = false
  let heightInvalid = false
  const specs = series?.specs || {}
  const name = series?.name || series?.id || 'This series'
  const w = Number(width) || 0
  const h = Number(height) || 0

  const availableWidths = specs.availableWidths
  if (availableWidths?.length && !availableWidths.includes(w)) {
    errors.push(
      `${name} is not available in width ${formatFtIn(w)}. Available widths: ${formatFtInList(availableWidths)}.`
    )
    widthInvalid = true
  } else if (specs.maxWidth && w > specs.maxWidth) {
    errors.push(`Door width ${w}" exceeds maximum ${specs.maxWidth}" for ${name}`)
    widthInvalid = true
  }

  const availableHeights = specs.availableHeights
  if (availableHeights?.length && !availableHeights.includes(h)) {
    errors.push(
      `${name} is not available in height ${formatFtIn(h)}. Available heights: ${formatFtInList(availableHeights)}.`
    )
    heightInvalid = true
  } else if (specs.maxHeight && h > specs.maxHeight) {
    errors.push(`Door height ${h}" exceeds maximum ${specs.maxHeight}" for ${name}`)
    heightInvalid = true
  }

  return { errors, widthInvalid, heightInvalid }
}

export function collectDoorsDimensionErrors(doors, config) {
  const out = []
  const list = doors || []
  for (let i = 0; i < list.length; i++) {
    const door = list[i]
    const series = lookupSeries(config, door)
    const { errors } = getDimensionValidation(series, door?.doorWidth, door?.doorHeight)
    for (const msg of errors) {
      out.push(list.length > 1 ? `Door ${i + 1}: ${msg}` : msg)
    }
  }
  return out
}
