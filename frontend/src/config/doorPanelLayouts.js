/**
 * Door Panel Layout Specifications
 * Defines exact stamp/panel counts for each door size and design combination
 *
 * IMPORTANT: Stamp SIZE is fixed - only the COUNT changes per door size
 *
 * Format: Each design has entries for standard sizes
 * { columns: X, rows: Y } where:
 *   - columns = number of stamps horizontally per section
 *   - rows = number of sections (typically 4 for 7' doors)
 */

// =============================================================================
// SHERIDAN (SH) - Short raised panels
// =============================================================================
const SH_LAYOUTS = {
  // Width x Height (in feet) -> { columns per section }
  '8x7':  { columns: 4, rows: 4 },   // 4 stamps wide × 4 sections
  '9x7':  { columns: 4, rows: 4 },   // TODO: Verify - is this 4 or 5?
  '10x7': { columns: 5, rows: 4 },   // TODO: Verify
  '12x7': { columns: 6, rows: 4 },   // TODO: Verify
  '14x7': { columns: 7, rows: 4 },   // TODO: Verify
  '16x7': { columns: 8, rows: 4 },   // TODO: Verify
  '18x7': { columns: 9, rows: 4 },   // TODO: Verify
  // 8' tall doors
  '8x8':  { columns: 4, rows: 4 },   // TODO: Verify rows
  '9x8':  { columns: 4, rows: 4 },   // TODO: Verify
  '10x8': { columns: 5, rows: 4 },   // TODO: Verify
  '12x8': { columns: 6, rows: 4 },   // TODO: Verify
  '16x8': { columns: 8, rows: 4 },   // TODO: Verify
}

// =============================================================================
// SHERIDAN XL (SHXL) - Long raised panels
// =============================================================================
const SHXL_LAYOUTS = {
  '8x7':  { columns: 2, rows: 4 },   // 2 long stamps × 4 sections
  '9x7':  { columns: 2, rows: 4 },   // TODO: Verify - is this 2 or 3?
  '10x7': { columns: 2, rows: 4 },   // TODO: Verify
  '12x7': { columns: 3, rows: 4 },   // TODO: Verify
  '14x7': { columns: 3, rows: 4 },   // TODO: Verify
  '16x7': { columns: 4, rows: 4 },   // TODO: Verify
  '18x7': { columns: 4, rows: 4 },   // TODO: Verify
  // 8' tall doors
  '8x8':  { columns: 2, rows: 4 },   // TODO: Verify
  '9x8':  { columns: 2, rows: 4 },   // TODO: Verify
  '10x8': { columns: 2, rows: 4 },   // TODO: Verify
  '12x8': { columns: 3, rows: 4 },   // TODO: Verify
  '16x8': { columns: 4, rows: 4 },   // TODO: Verify
}

// =============================================================================
// BRONTE CREEK (BC) - Carriage house short panels with vertical grooves
// =============================================================================
const BC_LAYOUTS = {
  '8x7':  { columns: 4, rows: 4, groovesPerStamp: 3 },
  '9x7':  { columns: 4, rows: 4, groovesPerStamp: 3 },   // TODO: Verify
  '10x7': { columns: 5, rows: 4, groovesPerStamp: 3 },   // TODO: Verify
  '12x7': { columns: 6, rows: 4, groovesPerStamp: 3 },   // TODO: Verify
  '14x7': { columns: 7, rows: 4, groovesPerStamp: 3 },   // TODO: Verify
  '16x7': { columns: 8, rows: 4, groovesPerStamp: 3 },   // TODO: Verify
  '18x7': { columns: 9, rows: 4, groovesPerStamp: 3 },   // TODO: Verify
}

// =============================================================================
// BRONTE CREEK XL (BCXL) - Carriage house long panels with vertical grooves
// =============================================================================
const BCXL_LAYOUTS = {
  '8x7':  { columns: 2, rows: 4, groovesPerStamp: 5 },
  '9x7':  { columns: 2, rows: 4, groovesPerStamp: 5 },   // TODO: Verify
  '10x7': { columns: 2, rows: 4, groovesPerStamp: 5 },   // TODO: Verify
  '12x7': { columns: 3, rows: 4, groovesPerStamp: 5 },   // TODO: Verify
  '14x7': { columns: 3, rows: 4, groovesPerStamp: 5 },   // TODO: Verify
  '16x7': { columns: 4, rows: 4, groovesPerStamp: 5 },   // TODO: Verify
  '18x7': { columns: 4, rows: 4, groovesPerStamp: 5 },   // TODO: Verify
}

// =============================================================================
// TRAFALGAR (TRAF) - Horizontal ribbed (no stamps, just ribs)
// =============================================================================
const TRAF_LAYOUTS = {
  // Trafalgar doesn't have stamps - just continuous horizontal ribs
  // ribsPerSection = number of horizontal rib lines per section
  '8x7':  { columns: 1, rows: 4, ribsPerSection: 18 },
  '9x7':  { columns: 1, rows: 4, ribsPerSection: 18 },
  '10x7': { columns: 1, rows: 4, ribsPerSection: 18 },
  '12x7': { columns: 1, rows: 4, ribsPerSection: 18 },
  '16x7': { columns: 1, rows: 4, ribsPerSection: 18 },
}

// =============================================================================
// FLUSH - Smooth panels (no stamps)
// =============================================================================
const FLUSH_LAYOUTS = {
  // Flush has no stamps - just smooth sections
  '8x7':  { columns: 1, rows: 4 },
  '9x7':  { columns: 1, rows: 4 },
  '10x7': { columns: 1, rows: 4 },
  '12x7': { columns: 1, rows: 4 },
  '16x7': { columns: 1, rows: 4 },
}

// =============================================================================
// CRAFT SERIES - Muskoka, Denison, Granville
// =============================================================================
const MUSKOKA_LAYOUTS = {
  // Muskoka has X-brace pattern - always 2 panels (left/right)
  '8x7':  { columns: 2, rows: 4 },
  '9x7':  { columns: 2, rows: 4 },
  '10x7': { columns: 2, rows: 4 },
  '12x7': { columns: 2, rows: 4 },
  '16x7': { columns: 2, rows: 4 },
}

const DENISON_LAYOUTS = {
  // Denison has vertical narrow panels
  '8x7':  { columns: 8, rows: 4 },   // TODO: Verify count
  '9x7':  { columns: 9, rows: 4 },   // TODO: Verify
  '10x7': { columns: 10, rows: 4 },  // TODO: Verify
  '12x7': { columns: 12, rows: 4 },  // TODO: Verify
  '16x7': { columns: 16, rows: 4 },  // TODO: Verify
}

const GRANVILLE_LAYOUTS = {
  // Granville similar to Denison
  '8x7':  { columns: 8, rows: 4 },   // TODO: Verify count
  '9x7':  { columns: 9, rows: 4 },   // TODO: Verify
  '10x7': { columns: 10, rows: 4 },  // TODO: Verify
  '12x7': { columns: 12, rows: 4 },  // TODO: Verify
  '16x7': { columns: 16, rows: 4 },  // TODO: Verify
}

// =============================================================================
// MASTER LOOKUP
// =============================================================================
const PANEL_LAYOUTS = {
  SH: SH_LAYOUTS,
  SHXL: SHXL_LAYOUTS,
  BC: BC_LAYOUTS,
  BCXL: BCXL_LAYOUTS,
  TRAF: TRAF_LAYOUTS,
  FLUSH: FLUSH_LAYOUTS,
  MUSKOKA: MUSKOKA_LAYOUTS,
  DENISON: DENISON_LAYOUTS,
  GRANVILLE: GRANVILLE_LAYOUTS,
}

/**
 * Get panel layout for a specific door configuration
 * @param {string} designCode - Design code (SH, SHXL, BC, etc.)
 * @param {number} widthInches - Door width in inches
 * @param {number} heightInches - Door height in inches
 * @returns {object} Layout with columns, rows, and design-specific properties
 */
export function getPanelLayout(designCode, widthInches, heightInches) {
  const widthFeet = Math.round(widthInches / 12)
  const heightFeet = Math.round(heightInches / 12)
  const sizeKey = `${widthFeet}x${heightFeet}`

  const designLayouts = PANEL_LAYOUTS[designCode]
  if (!designLayouts) {
    // Fallback for unknown designs
    return { columns: 4, rows: 4 }
  }

  const layout = designLayouts[sizeKey]
  if (!layout) {
    // Fallback: find closest size or use default
    // Try to find any layout for this design
    const defaultKey = Object.keys(designLayouts)[0]
    return designLayouts[defaultKey] || { columns: 4, rows: 4 }
  }

  return layout
}

/**
 * Get all available sizes for a design
 */
export function getAvailableSizes(designCode) {
  const designLayouts = PANEL_LAYOUTS[designCode]
  if (!designLayouts) return []
  return Object.keys(designLayouts)
}

export {
  PANEL_LAYOUTS,
  SH_LAYOUTS,
  SHXL_LAYOUTS,
  BC_LAYOUTS,
  BCXL_LAYOUTS,
  TRAF_LAYOUTS,
  FLUSH_LAYOUTS,
  MUSKOKA_LAYOUTS,
  DENISON_LAYOUTS,
  GRANVILLE_LAYOUTS,
}

export default {
  getPanelLayout,
  getAvailableSizes,
  PANEL_LAYOUTS,
}
