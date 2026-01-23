/**
 * Window Specifications Configuration
 * Defines window dimensions and styles for each door series
 * All dimensions in inches for proportional rendering
 */

// =============================================================================
// KANATA WINDOWS (5 sizes) - Also used by Executive series
// =============================================================================
export const KANATA_WINDOWS = {
  LONG_PANEL: {
    id: 'LONG_PANEL',
    name: 'Long Panel',
    width: 40,
    height: 14,
    series: 'kanata',
    description: 'Standard long panel window'
  },
  SHORT_PANEL: {
    id: 'SHORT_PANEL',
    name: 'Short Panel',
    width: 20,
    height: 14,
    series: 'kanata',
    description: 'Standard short panel window'
  },
  SLIM_LONG: {
    id: 'SLIM_LONG',
    name: 'Slim Long',
    width: 64,
    height: 7,
    series: 'kanata',
    description: 'Slim long horizontal window'
  },
  SLIM_MEDIUM: {
    id: 'SLIM_MEDIUM',
    name: 'Slim Medium',
    width: 41,
    height: 7,
    series: 'kanata',
    description: 'Slim medium horizontal window'
  },
  SLIM_SMALL: {
    id: 'SLIM_SMALL',
    name: 'Slim Small',
    width: 24,
    height: 7,
    series: 'kanata',
    description: 'Slim small horizontal window'
  },
}

// =============================================================================
// CRAFT SERIES WINDOWS (1 size)
// =============================================================================
export const CRAFT_WINDOWS = {
  CRAFT: {
    id: 'CRAFT',
    name: 'Craft Window',
    width: 42,
    height: 18,
    series: 'craft',
    description: 'Standard craft series window'
  },
}

// =============================================================================
// COMMERCIAL WINDOWS (2 sizes)
// =============================================================================
export const COMMERCIAL_WINDOWS = {
  STANDARD: {
    id: 'COMMERCIAL_STANDARD',
    name: 'Standard Commercial',
    width: 24,
    height: 12,
    series: 'commercial',
    description: 'Standard commercial window'
  },
  LARGE: {
    id: 'COMMERCIAL_LARGE',
    name: 'Large Commercial',
    width: 36,
    height: 16,
    series: 'commercial',
    description: 'Large commercial window'
  },
}

// =============================================================================
// WINDOW GLASS STYLES (muntin patterns)
// =============================================================================
export const GLASS_STYLES = {
  PLAIN: {
    id: 'PLAIN',
    name: 'Plain Glass',
    description: 'Clear glass without muntins'
  },
  STOCKTON: {
    id: 'STOCKTON',
    name: 'Stockton',
    description: 'Colonial grid pattern'
  },
  STOCKTON_ARCHED: {
    id: 'STOCKTON_ARCHED',
    name: 'Stockton Arched',
    description: 'Colonial grid with arched top'
  },
  STOCKBRIDGE: {
    id: 'STOCKBRIDGE',
    name: 'Stockbridge',
    description: 'Prairie style corner pattern'
  },
  STOCKBRIDGE_ARCHED: {
    id: 'STOCKBRIDGE_ARCHED',
    name: 'Stockbridge Arched',
    description: 'Prairie style with arched top'
  },
  WATERTON: {
    id: 'WATERTON',
    name: 'Waterton',
    description: 'Vertical bar pattern'
  },
  SHERWOOD: {
    id: 'SHERWOOD',
    name: 'Sherwood',
    description: 'Diamond lattice pattern'
  },
}

// =============================================================================
// MASTER WINDOW LOOKUP BY DOOR SERIES
// =============================================================================
export const WINDOWS_BY_SERIES = {
  // Kanata Collection
  SH: KANATA_WINDOWS,
  SHXL: KANATA_WINDOWS,
  BC: KANATA_WINDOWS,
  BCXL: KANATA_WINDOWS,
  TRAF: KANATA_WINDOWS,
  FLUSH: KANATA_WINDOWS,

  // Craft Series
  MUSKOKA: CRAFT_WINDOWS,
  DENISON: CRAFT_WINDOWS,
  GRANVILLE: CRAFT_WINDOWS,

  // Executive Series (uses Kanata windows)
  EXECUTIVE: KANATA_WINDOWS,

  // Commercial
  COMMERCIAL: COMMERCIAL_WINDOWS,
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Get available windows for a door design
 * @param {string} panelDesign - Door panel design code (SH, BC, MUSKOKA, etc.)
 * @returns {object} Available windows for that design
 */
export function getWindowsForDesign(panelDesign) {
  return WINDOWS_BY_SERIES[panelDesign] || KANATA_WINDOWS
}

/**
 * Get window specification by ID
 * @param {string} windowId - Window ID
 * @returns {object|null} Window specification
 */
export function getWindowSpec(windowId) {
  // Search all window collections
  const allWindows = { ...KANATA_WINDOWS, ...CRAFT_WINDOWS, ...COMMERCIAL_WINDOWS }
  return allWindows[windowId] || null
}

/**
 * Calculate how many windows fit in a door section
 * @param {number} doorWidthInches - Door width in inches
 * @param {number} windowWidthInches - Window width in inches
 * @param {number} minGap - Minimum gap between windows in inches
 * @returns {number} Number of windows that fit
 */
export function calculateWindowCount(doorWidthInches, windowWidthInches, minGap = 2) {
  const availableWidth = doorWidthInches - (minGap * 2) // Account for edge margins
  return Math.floor((availableWidth + minGap) / (windowWidthInches + minGap))
}

/**
 * Calculate window positions for centering in a section
 * @param {number} doorWidthInches - Door width in inches
 * @param {number} windowWidthInches - Window width in inches
 * @param {number} windowCount - Number of windows
 * @param {number} gap - Gap between windows in inches
 * @returns {number[]} Array of x positions (in inches from left edge)
 */
export function calculateWindowPositions(doorWidthInches, windowWidthInches, windowCount, gap = 2) {
  const totalWindowsWidth = windowCount * windowWidthInches + (windowCount - 1) * gap
  const startX = (doorWidthInches - totalWindowsWidth) / 2

  const positions = []
  for (let i = 0; i < windowCount; i++) {
    positions.push(startX + i * (windowWidthInches + gap))
  }
  return positions
}

/**
 * Get all windows as flat array for selection UI
 * @param {string} panelDesign - Optional filter by door design
 * @returns {object[]} Array of window specs
 */
export function getWindowOptions(panelDesign = null) {
  if (panelDesign) {
    const windows = getWindowsForDesign(panelDesign)
    return Object.values(windows)
  }

  // Return all unique windows
  const allWindows = { ...KANATA_WINDOWS, ...CRAFT_WINDOWS, ...COMMERCIAL_WINDOWS }
  return Object.values(allWindows)
}

export default {
  KANATA_WINDOWS,
  CRAFT_WINDOWS,
  COMMERCIAL_WINDOWS,
  GLASS_STYLES,
  WINDOWS_BY_SERIES,
  getWindowsForDesign,
  getWindowSpec,
  calculateWindowCount,
  calculateWindowPositions,
  getWindowOptions,
}
