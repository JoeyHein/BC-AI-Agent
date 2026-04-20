/**
 * Door Extras Derivation
 *
 * Produces the human-readable list of "OPTIONAL EXTRAS" shown on the
 * framing drawing, based on what was actually selected for this order.
 *
 * Two entry points:
 *   - extrasFromConfig(doorConfig): derive from live configurator state
 *   - extrasFromLineItems(lineItems): derive from BC sales order/quote lines
 *
 * Both return a deduplicated array of uppercase strings.
 */

const LIFT_LABELS = {
  standard: 'STANDARD LIFT',
  high_lift: 'HIGH LIFT',
  vertical: 'VERTICAL LIFT',
  low_headroom: 'LOW HEADROOM',
}

export function extrasFromConfig(doorConfig = {}) {
  const items = []
  const cfg = doorConfig

  const ts = parseInt(cfg.trackThickness) || 2
  items.push(`${ts}" TRACK APPLICATION`)

  const isResidential = (cfg.doorType || 'residential') === 'residential'
  items.push(isResidential ? 'WOOD FRAME' : 'STEEL FRAME')

  items.push(cfg.trackMount === 'angle' ? 'CONTINUOUS ANGLE MOUNT' : 'BRACKET MOUNT')

  if (LIFT_LABELS[cfg.liftType]) items.push(LIFT_LABELS[cfg.liftType])
  if (cfg.liftType === 'high_lift' && cfg.highLiftInches) {
    items.push(`${cfg.highLiftInches}" HIGH LIFT`)
  }

  if (cfg.trackRadius) items.push(`${cfg.trackRadius}" RADIUS TRACK`)

  const cycles = parseInt(cfg.targetCycles) || 0
  if (cycles >= 100000) items.push('100,000 CYCLE SPRING')
  else if (cycles >= 50000) items.push('50,000 CYCLE SPRING')
  else if (cycles >= 25000) items.push('25,000 CYCLE SPRING')

  if (cfg.springCount === 2) items.push('DOUBLE LIFE SPRING')

  if (cfg.shaftType === 'split') items.push('SPLIT SHAFT')

  const hw = cfg.hardware || {}
  if (hw.struts) items.push('DOOR STRUTS')
  if (hw.weatherStripping) items.push('TOP SEAL VINYL')
  if (hw.bottomRetainer) items.push('RUBBER ASTRAGAL')

  if (cfg.operator && cfg.operator !== 'NONE') {
    items.push('ELECTRIC OPERATOR')
  }

  if (Array.isArray(cfg.operatorAccessories)) {
    for (const acc of cfg.operatorAccessories) {
      const a = String(acc).toUpperCase()
      if (a.includes('KEYPAD')) items.push('KEYPAD')
      if (a.includes('REMOTE')) items.push('REMOTE CONTROL')
      if (a.includes('PHOTO')) items.push('PHOTO EYES')
    }
  }

  return dedupe(items)
}

// Part-prefix / keyword rules for BC line items.
// Order matters only for which label wins on the first match per line.
const LINE_RULES = [
  { test: (i, d) => /^FH17/.test(i) || d.includes('STRUT'), label: 'DOOR STRUTS' },
  { test: (i, d) => d.includes('OPERATOR') || /^OP/.test(i) || d.includes('LIFTMASTER') || d.includes('CHAMBERLAIN'), label: 'ELECTRIC OPERATOR' },
  { test: (i, d) => d.includes('KEYPAD'), label: 'KEYPAD' },
  { test: (i, d) => d.includes('REMOTE'), label: 'REMOTE CONTROL' },
  { test: (i, d) => d.includes('PHOTO EYE') || d.includes('PHOTOEYE'), label: 'PHOTO EYES' },
  { test: (i, d) => d.includes('KEYED') && d.includes('LOCK'), label: 'KEYED SIDE LOCK' },
  { test: (i, d) => d.includes('SLIDE LOCK') || d.includes('SIDE LOCK'), label: 'SIDE LOCK' },
  { test: (i, d) => /^PL10-00005/.test(i) || d.includes('ASTRAGAL'), label: 'RUBBER ASTRAGAL' },
  { test: (i, d) => d.includes('TOP SEAL') || /^PL10.*203/.test(i), label: 'TOP SEAL VINYL' },
  { test: (i, d) => d.includes('DECORATIVE') && d.includes('HARDWARE'), label: 'DECORATIVE HARDWARE' },
  { test: (i, d) => /^SH/.test(i) || d.includes('TUBULAR SHAFT'), label: '1" TUBULAR SHAFT' },
  { test: (i, d) => d.includes('END STILE') || d.includes('END HINGE'), label: 'END STILE/HINGE' },
]

export function extrasFromLineItems(lineItems = []) {
  const items = []

  // Spring count detection: total qty of SP** lines
  let springQty = 0
  let highestCycle = 0

  for (const line of lineItems) {
    const itemNo = String(line.item_number || line.itemNumber || '').toUpperCase()
    const desc = String(line.description || '').toUpperCase()
    const qty = Number(line.quantity) || 0

    if (/^SP\d/.test(itemNo)) springQty += qty

    // Cycle rating often encoded in description: "50,000 CYCLE" or "25K CYCLE"
    const cycleMatch = desc.match(/(\d[\d,]*)\s*(?:K\s*)?CYCLE/)
    if (cycleMatch) {
      const n = parseInt(cycleMatch[1].replace(/,/g, ''), 10)
      const cycles = cycleMatch[0].includes('K') ? n * 1000 : n
      if (cycles > highestCycle) highestCycle = cycles
    }

    for (const rule of LINE_RULES) {
      if (rule.test(itemNo, desc)) {
        items.push(rule.label)
        break
      }
    }
  }

  if (springQty >= 2) items.push('DOUBLE LIFE SPRING')
  if (highestCycle >= 100000) items.push('100,000 CYCLE SPRING')
  else if (highestCycle >= 50000) items.push('50,000 CYCLE SPRING')
  else if (highestCycle >= 25000) items.push('25,000 CYCLE SPRING')

  return dedupe(items)
}

function dedupe(arr) {
  const seen = new Set()
  const out = []
  for (const s of arr) {
    if (!seen.has(s)) { seen.add(s); out.push(s) }
  }
  return out
}
