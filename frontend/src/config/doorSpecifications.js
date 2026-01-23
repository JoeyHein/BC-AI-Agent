/**
 * Door Specifications Configuration
 * Contains RAL color codes, stamp dimensions, and panel layout specifications
 * Based on Upwardor Digital Catalogue analysis
 *
 * KEY INSIGHT: Stamp/panel sizes are FIXED - only spacing and quantity change with door width
 */

// ============================================================================
// RAL COLOR CODES - Standard Upwardor Colors
// ============================================================================
export const COLOR_SPECIFICATIONS = {
  // White/Light Colors
  WHITE: {
    hex: '#FFFFFF',
    ral: 'RAL 9010',
    name: 'Pure White',
    type: 'solid',
    description: 'Standard pure white finish'
  },
  BRIGHT_WHITE: {
    hex: '#FFFFFF',
    ral: 'RAL 9016',
    name: 'Traffic White',
    type: 'solid',
    description: 'Bright traffic white'
  },
  NEW_ALMOND: {
    hex: '#EFDECD',
    ral: 'RAL 1015',
    name: 'Light Ivory',
    type: 'solid',
    description: 'Light almond/ivory tone'
  },
  SANDTONE: {
    hex: '#C2B280',
    ral: 'RAL 1001',
    name: 'Beige',
    type: 'solid',
    description: 'Sandy beige tone'
  },

  // Dark Colors
  BLACK: {
    hex: '#1A1A1A',
    ral: 'RAL 9005',
    name: 'Jet Black',
    type: 'solid',
    description: 'Deep black finish'
  },
  IRON_ORE: {
    hex: '#48464A',
    ral: 'RAL 7024',
    name: 'Graphite Grey',
    type: 'solid',
    description: 'Dark iron/graphite grey'
  },
  STEEL_GREY: {
    hex: '#71797E',
    ral: 'RAL 7046',
    name: 'Telegrey 2',
    type: 'solid',
    description: 'Medium steel grey'
  },

  // Brown/Wood Tones
  NEW_BROWN: {
    hex: '#4A3728',
    ral: 'RAL 8011',
    name: 'Nut Brown',
    type: 'solid',
    description: 'Medium brown tone'
  },
  BRONZE: {
    hex: '#80461B',
    ral: 'RAL 8001',
    name: 'Ochre Brown',
    type: 'solid',
    description: 'Bronze/ochre finish'
  },

  // Wood Grain Laminates
  WALNUT: {
    hex: '#5D432C',
    ral: null,
    name: 'Walnut Woodgrain',
    type: 'woodgrain',
    baseColor: '#5D432C',
    grainColor: '#3D2A1A',
    description: 'Walnut wood laminate'
  },
  HAZELWOOD: {
    hex: '#8E7618',
    ral: null,
    name: 'Hazelwood Woodgrain',
    type: 'woodgrain',
    baseColor: '#8E7618',
    grainColor: '#6D5A12',
    description: 'Hazelwood laminate'
  },
  ENGLISH_CHESTNUT: {
    hex: '#954535',
    ral: null,
    name: 'English Chestnut',
    type: 'woodgrain',
    baseColor: '#954535',
    grainColor: '#6B3025',
    description: 'Rich chestnut wood laminate'
  },
  MEDIUM_OAK: {
    hex: '#B5833E',
    ral: null,
    name: 'Medium Oak',
    type: 'woodgrain',
    baseColor: '#B5833E',
    grainColor: '#8A632E',
    description: 'Medium oak wood laminate'
  },
  DARK_WALNUT: {
    hex: '#3D2A1A',
    ral: null,
    name: 'Dark Walnut',
    type: 'woodgrain',
    baseColor: '#3D2A1A',
    grainColor: '#2A1D12',
    description: 'Dark walnut wood laminate'
  },
  NATURAL: {
    hex: '#D4A574',
    ral: null,
    name: 'Natural Wood',
    type: 'woodgrain',
    baseColor: '#D4A574',
    grainColor: '#A78450',
    description: 'Light natural wood tone'
  },

  // Specialty
  CLEAR_ANODIZED: {
    hex: '#C0C0C0',
    ral: 'RAL 9006',
    name: 'White Aluminum',
    type: 'metallic',
    description: 'Clear anodized aluminum finish'
  },
}

// ============================================================================
// STAMP/PANEL DIMENSIONS - FIXED SIZES (in inches)
// ============================================================================
export const STAMP_DIMENSIONS = {
  // Sheridan (SH) - Short raised panels
  SH: {
    stampWidth: 21,      // Fixed stamp width in inches
    stampHeight: 17,     // Fixed stamp height in inches (within 21" section)
    insetDepth: 0.75,    // Depth of raised panel inset
    bevelWidth: 0.5,     // Width of beveled edge
    description: 'Short raised rectangular panels'
  },

  // Sheridan XL (SHXL) - Long raised panels
  SHXL: {
    stampWidth: 42,      // Fixed stamp width (2x normal width)
    stampHeight: 17,
    insetDepth: 0.75,
    bevelWidth: 0.5,
    description: 'Long horizontal raised panels'
  },

  // Bronte Creek (BC) - Carriage house short
  BC: {
    stampWidth: 21,
    stampHeight: 17,
    boardCount: 3,       // Vertical groove lines per panel
    grooveDepth: 0.25,
    description: 'Carriage house with vertical board grooves'
  },

  // Bronte Creek XL (BCXL) - Carriage house long
  BCXL: {
    stampWidth: 42,
    stampHeight: 17,
    boardCount: 5,       // More boards for wider panels
    grooveDepth: 0.25,
    description: 'Long carriage house with vertical boards'
  },

  // Trafalgar (TRAF) - Horizontal ribbed
  TRAF: {
    ribHeight: 1.5,      // Height of each rib
    ribSpacing: 1.75,    // Space between ribs
    ribsPerSection: 12,  // Approximate ribs per 21" section
    description: 'Fine horizontal ribbed texture'
  },

  // Flush (FLUSH) - Smooth surface
  FLUSH: {
    // No stamps - smooth panel with subtle texture
    textureType: 'pebble',
    description: 'Smooth pebble-embossed surface'
  },

  // Muskoka - X-brace barn door
  MUSKOKA: {
    panelWidth: 42,      // Each X-brace panel is half door width
    braceWidth: 2,       // Width of X-brace members
    description: 'X-brace barn door style'
  },

  // Denison - Vertical panels
  DENISON: {
    stampWidth: 10.5,    // Narrow vertical panels
    stampHeight: 17,
    grooveDepth: 0.5,
    description: 'Vertical recessed rectangle panels'
  },

  // Granville - Similar to Denison
  GRANVILLE: {
    stampWidth: 10.5,
    stampHeight: 17,
    grooveDepth: 0.5,
    description: 'Narrow vertical recessed panels'
  },
}

// ============================================================================
// PANEL LAYOUT CALCULATOR
// Returns number of columns based on door width
// ============================================================================
export function calculatePanelLayout(designCode, widthInches) {
  const specs = STAMP_DIMENSIONS[designCode]
  if (!specs) return { columns: 4, spacing: 0 }

  // Calculate based on fixed stamp width
  let stampWidth = specs.stampWidth || 21

  // For flush and ribbed, no columns needed
  if (designCode === 'FLUSH' || designCode === 'TRAF') {
    return { columns: 1, spacing: 0, fullWidth: true }
  }

  // For Muskoka, always 2 panels (left/right)
  if (designCode === 'MUSKOKA') {
    return { columns: 2, spacing: 0 }
  }

  // Calculate number of stamps that fit
  const availableWidth = widthInches - 2  // Account for frame edges
  const numColumns = Math.round(availableWidth / stampWidth)

  // Calculate actual spacing between stamps
  const totalStampWidth = numColumns * stampWidth
  const totalSpacing = availableWidth - totalStampWidth
  const spacingPerGap = totalSpacing / (numColumns + 1)

  return {
    columns: numColumns,
    stampWidth: stampWidth,
    spacing: spacingPerGap,
    totalWidth: availableWidth,
  }
}

// ============================================================================
// SECTION HEIGHT SPECIFICATIONS
// Standard residential door section heights
// ============================================================================
export const SECTION_HEIGHTS = {
  // Standard sections are 21" high
  STANDARD: 21,
  // XL sections are 24" high
  XL: 24,
}

export function calculateSectionLayout(heightInches) {
  // Residential doors: sections are typically 21" each
  // 7' door = 84" = 4 sections × 21"
  // 8' door = 96" ≈ 4 sections × 24" or 5 sections

  let sectionHeight = SECTION_HEIGHTS.STANDARD
  let numSections = Math.round(heightInches / sectionHeight)

  // Adjust for common door heights
  if (heightInches <= 84) {
    numSections = 4
    sectionHeight = heightInches / 4
  } else if (heightInches <= 96) {
    numSections = 4
    sectionHeight = heightInches / 4  // 24" sections
  } else if (heightInches <= 120) {
    numSections = 5
    sectionHeight = heightInches / 5
  } else if (heightInches <= 144) {
    numSections = 6
    sectionHeight = heightInches / 6
  } else if (heightInches <= 168) {
    numSections = 7
    sectionHeight = heightInches / 7
  } else {
    numSections = 8
    sectionHeight = heightInches / 8
  }

  return {
    numSections,
    sectionHeight,
    totalHeight: heightInches,
  }
}

// ============================================================================
// STANDARD DOOR SIZES (width × height in inches)
// ============================================================================
export const STANDARD_SIZES = {
  residential: [
    { width: 96, height: 84, label: "8' × 7'" },
    { width: 108, height: 84, label: "9' × 7'" },
    { width: 120, height: 84, label: "10' × 7'" },
    { width: 144, height: 84, label: "12' × 7'" },
    { width: 168, height: 84, label: "14' × 7'" },
    { width: 192, height: 84, label: "16' × 7'" },
    { width: 216, height: 84, label: "18' × 7'" },
    { width: 96, height: 96, label: "8' × 8'" },
    { width: 108, height: 96, label: "9' × 8'" },
    { width: 120, height: 96, label: "10' × 8'" },
    { width: 144, height: 96, label: "12' × 8'" },
    { width: 168, height: 96, label: "14' × 8'" },
    { width: 192, height: 96, label: "16' × 8'" },
  ],
  commercial: [
    { width: 120, height: 120, label: "10' × 10'" },
    { width: 144, height: 120, label: "12' × 10'" },
    { width: 144, height: 144, label: "12' × 12'" },
    { width: 168, height: 144, label: "14' × 12'" },
    { width: 192, height: 144, label: "16' × 12'" },
    { width: 192, height: 168, label: "16' × 14'" },
  ],
}

// ============================================================================
// HELPER: Get color specification
// ============================================================================
export function getColorSpec(colorId) {
  return COLOR_SPECIFICATIONS[colorId] || COLOR_SPECIFICATIONS.WHITE
}

// ============================================================================
// HELPER: Check if color is dark (for contrast calculations)
// ============================================================================
export function isColorDark(colorId) {
  const darkColors = ['BLACK', 'WALNUT', 'IRON_ORE', 'NEW_BROWN', 'ENGLISH_CHESTNUT',
                      'HAZELWOOD', 'BRONZE', 'DARK_WALNUT']
  return darkColors.includes(colorId)
}

// ============================================================================
// HELPER: Check if color is woodgrain
// ============================================================================
export function isColorWoodgrain(colorId) {
  const spec = COLOR_SPECIFICATIONS[colorId]
  return spec?.type === 'woodgrain'
}

export default {
  COLOR_SPECIFICATIONS,
  STAMP_DIMENSIONS,
  SECTION_HEIGHTS,
  STANDARD_SIZES,
  calculatePanelLayout,
  calculateSectionLayout,
  getColorSpec,
  isColorDark,
  isColorWoodgrain,
}
