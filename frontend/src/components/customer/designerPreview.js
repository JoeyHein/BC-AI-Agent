/**
 * Map a dealer quote door onto the shared door renderer.
 * The drawing reads this object on every option change, so the preview
 * stays in step with the door the customer is editing.
 */

export function previewPropsFromDoor(door) {
  const source = door || {}
  const doorType = source.doorType || 'residential'
  const aluminum = doorType === 'aluminium'
  const commercial = doorType === 'commercial'
  const showWindows = aluminum || Boolean(source.hasWindows)
  const insert = source.windowInsert && source.windowInsert !== 'NONE'
    ? source.windowInsert
    : null

  let panelDesign = source.panelDesign
  if (!panelDesign) {
    if (commercial) panelDesign = 'UDC'
    else if (aluminum) panelDesign = 'FLUSH'
    else panelDesign = 'SHXL'
  }

  return {
    width: source.doorWidth || 96,
    height: source.doorHeight || 84,
    color: source.panelColor || (aluminum ? 'CLEAR_ANODIZED' : 'WHITE'),
    panelDesign,
    doorType,
    doorSeries: source.doorSeries || '',
    windowInsert: showWindows ? insert : null,
    windowPositions: showWindows ? (source.windowPositions || []) : [],
    windowSection: source.windowSection || 1,
    windowSize: source.windowSize || 'long',
    hasInserts: showWindows && Boolean(source.hasInserts),
    glassColor: source.glassColor || 'CLEAR',
    windowQty: showWindows ? (source.windowQty || 0) : 0,
    windowPanels: showWindows ? (source.windowPanels || null) : null,
    windowFrameColor: source.windowFrameColor || (commercial ? 'BLACK' : 'MATCH'),
    glassPocketsPerSection: source.glassPocketsPerSection || null,
    showDimensions: true,
  }
}

/** Every door needs a series and a size before a running price is meaningful. */
export function quoteReadyForPreview(doors) {
  if (!Array.isArray(doors) || doors.length === 0) return false
  return doors.every((door) => (
    door
    && door.doorSeries
    && Number(door.doorWidth) > 0
    && Number(door.doorHeight) > 0
  ))
}

/**
 * Identity of the priced configuration. door_uid and UI scratch fields
 * do not change the price, so editing them must not refetch.
 */
export function priceSignature(doors, deliveryType) {
  const slim = (doors || []).map((door) => {
    if (!door) return null
    const copy = { ...door }
    delete copy.door_uid
    delete copy._touched
    delete copy.explicitFields
    return copy
  })
  return JSON.stringify({
    deliveryType: deliveryType || 'delivery',
    doors: slim,
  })
}

export function doorForPreviewPrice(door) {
  const preview = previewPropsFromDoor(door)
  return {
    ...(door || {}),
    panelColor: door?.panelColor || preview.color,
    panelDesign: door?.panelDesign || preview.panelDesign,
  }
}

export function formatDealerPrice(amount, currency = 'CAD') {
  return new Intl.NumberFormat('en-CA', {
    style: 'currency',
    currency: currency || 'CAD',
  }).format(amount || 0)
}
