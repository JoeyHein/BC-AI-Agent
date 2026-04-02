/**
 * DoorPreview Component
 * Renders a visual preview of the door configuration in real-time
 * Shows panel layout, colors, window placement, and design patterns
 */

import { useMemo } from 'react'

// Panel design patterns as SVG patterns
// Based on Upwardor stamp layouts

// Calculate number of stamp columns based on door width (in inches)
// Stamps are 42" long x 14" tall
// Based on Upwardor Long Raised Panel layout specifications
const STAMP_WIDTH = 42 // inches
const STAMP_HEIGHT = 14 // inches

const getStampColumns = (widthInches, stampType = 'long', isCraft = false, panelDesign = '') => {
  const widthFeet = widthInches / 12

  // Long stamps (SHXL, BCXL): ~42" wide
  let longCols
  if (widthFeet <= 10) longCols = 2
  else if (widthFeet <= 12) longCols = 3
  else if (widthFeet <= 16) longCols = 4
  else if (widthFeet <= 19) longCols = 5
  else longCols = 6

  if (isCraft) return longCols
  if (stampType === 'long') return longCols

  // Short stamps vary by design — SH and BC have different stamp widths
  // SH (Sheridan): ~21" stamps
  // BC (Bronte Creek): always in pairs of 2 stamps
  const isBronte = panelDesign === 'BC'
  if (isBronte) {
    // BC stamps always come in pairs: 2 pairs=4, 3 pairs=6, 4 pairs=8
    if (widthFeet <= 10) return 4   // 2 pairs
    if (widthFeet <= 14) return 6   // 3 pairs
    if (widthFeet <= 16) return 8   // 4 pairs
    if (widthFeet <= 18) return 8   // 4 pairs
    return 10                       // 5 pairs
  } else {
    // SH (default for standard stamps)
    if (widthFeet <= 9) return 4
    if (widthFeet <= 10) return 5
    if (widthFeet <= 12) return 6
    if (widthFeet <= 14) return 7
    if (widthFeet <= 16) return 8
    if (widthFeet <= 18) return 9
    return 10
  }
}

const PANEL_PATTERNS = {
  // Sheridan XL - Long raised panel (1 row, columns based on width)
  SHXL: {
    type: 'raised',
    rows: 1,
    cols: 'dynamic', // Will be calculated based on door width
    stampType: 'long',
    style: 'sheridan',
    description: 'Sheridan XL - Long Raised Panel'
  },
  // Sheridan - Short raised panel (1 row per section, more square stamps)
  SH: {
    type: 'raised',
    rows: 1,
    cols: 'dynamic',
    stampType: 'standard',
    style: 'sheridan',
    description: 'Sheridan - Short Raised Panel'
  },
  // Bronte Creek XL - Long carriage panel (1 row, columns based on width)
  BCXL: {
    type: 'carriage',
    rows: 1,
    cols: 'dynamic',
    stampType: 'long',
    style: 'bronte',
    description: 'Bronte Creek XL - Long Carriage Panel'
  },
  // Bronte Creek - Short carriage panel (1 row per section, more square stamps)
  BC: {
    type: 'carriage',
    rows: 1,
    cols: 'dynamic',
    stampType: 'standard',
    style: 'bronte',
    description: 'Bronte Creek - Short Carriage Panel'
  },
  // Trafalgar - Horizontal ribbed
  TRAFALGAR: {
    type: 'horizontal_ribbed',
    ribs: 5,
    style: 'modern',
    description: 'Trafalgar - Ribbed'
  },
  // Flush - Flat panel (no design)
  FLUSH: {
    type: 'flush',
    style: 'minimal',
    description: 'Flush - Flat Panel'
  },
  // UDC - Commercial standard (horizontal lines)
  UDC: {
    type: 'horizontal_ribbed',
    ribs: 5,
    style: 'commercial',
    description: 'UDC - Commercial Standard'
  },
  // Muskoka - X-brace barn door (Craft series)
  MUSKOKA: {
    type: 'xbrace',
    style: 'muskoka',
    description: 'Muskoka - X-Brace Barn Door'
  },
  // Denison - Raised panel grid (Craft series)
  DENISON: {
    type: 'raised_grid',
    style: 'denison',
    description: 'Denison - Raised Panel Grid'
  },
  // Granville - Raised panels wide (Craft series)
  GRANVILLE: {
    type: 'raised_grid',
    style: 'granville',
    description: 'Granville - Raised Panels (Wide)'
  },
}

// Color hex values - RAL codes for accurate representation
const COLOR_MAP = {
  // Solid colors (RAL)
  WHITE: '#F4F4F4',           // RAL 9003 Signal White
  BRIGHT_WHITE: '#F4F4F4',    // RAL 9003
  BLACK: '#282828',           // RAL 9004 Signal Black
  NEW_BROWN: '#4C4842',       // RAL 7022 Umbra Grey
  HAZELWOOD: '#756F61',       // RAL 7006 Beige Grey
  BRONZE: '#6C6961',          // RAL 7039 Quartz Grey
  STEEL_GREY: '#7D7F7D',      // RAL 7037 Dusty Grey
  SANDTONE: '#A4957D',        // RAL 1019 Grey Beige
  IRON_ORE: '#2F3234',        // RAL 7021 Black Grey
  // Woodgrain colors (base color for pattern)
  WALNUT: '#4A3728',
  ENGLISH_CHESTNUT: '#6B4423',
  FRENCH_OAK: '#C2B078',          // RAL 1001 Beige (light base)
  // Aluminum finishes
  CLEAR_ANODIZED: '#C0C0C0',
  BLACK_ANODIZED: '#1a1a1a',
  MILL: '#D3D3D3',
}

// Woodgrain patterns - colors for grain effect
const WOODGRAIN_COLORS = {
  WALNUT: { base: '#4A3728', light: '#5D432C', dark: '#3D2B1F' },
  ENGLISH_CHESTNUT: { base: '#6B4423', light: '#8B5A2B', dark: '#5C3317' },
  FRENCH_OAK: { base: '#C2B078', light: '#C2B078', dark: '#8A6642' },  // RAL 1001 light, RAL 1011 dark
}

// Check if a color is a woodgrain finish
const isWoodgrain = (colorId) => {
  return ['WALNUT', 'ENGLISH_CHESTNUT', 'FRENCH_OAK'].includes(colorId)
}

// Darken a hex color by a factor (0-1, where 0.8 = 80% brightness)
const darkenHex = (hex, factor = 0.75) => {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  const dr = Math.round(r * factor)
  const dg = Math.round(g * factor)
  const db = Math.round(b * factor)
  return `#${dr.toString(16).padStart(2, '0')}${dg.toString(16).padStart(2, '0')}${db.toString(16).padStart(2, '0')}`
}

// Resolve window frame color: 'MATCH' darkens door color, otherwise use COLOR_MAP lookup
const resolveFrameColor = (frameColorId, doorColorHex, doorColorId) => {
  if (frameColorId === 'MATCH' || !frameColorId) {
    // For woodgrain, use the dark grain color; for solids, darken the door color
    if (isWoodgrain(doorColorId) && WOODGRAIN_COLORS[doorColorId]) {
      return { fill: WOODGRAIN_COLORS[doorColorId].dark, stroke: darkenHex(WOODGRAIN_COLORS[doorColorId].dark, 0.7) }
    }
    return { fill: darkenHex(doorColorHex, 0.75), stroke: darkenHex(doorColorHex, 0.55) }
  }
  // Custom color from COLOR_MAP
  const hex = COLOR_MAP[frameColorId] || doorColorHex
  return { fill: hex, stroke: darkenHex(hex, 0.7) }
}

// Window insert shapes
// Residential window sizes (in inches)
// Windows fit within stamp areas
const WINDOW_SIZES = {
  LONG: { width: 40, height: 14 },   // 14x40 for SHXL/BCXL (fits 1 long stamp)
  SHORT: { width: 20, height: 14 },  // 14x20 for SH/BC (fits 1 short stamp)
}

// Window insert styles with grid patterns
const WINDOW_SHAPES = {
  // 14x40 windows (for SHXL/BCXL long stamps, or spans 2 stamps on SH/BC)
  STOCKTON_STANDARD: { type: 'grid', rows: 2, cols: 4, arched: false, size: 'LONG' },
  STOCKTON_TEN_SQUARE_XL: { type: 'grid', rows: 2, cols: 5, arched: false, size: 'LONG' },
  STOCKTON_ARCHED_XL: { type: 'grid', rows: 2, cols: 5, arched: true, size: 'LONG' },
  STOCKTON_EIGHT_SQUARE: { type: 'grid', rows: 2, cols: 4, arched: false, size: 'LONG' },
  STOCKTON_ARCHED: { type: 'grid', rows: 2, cols: 4, arched: true, size: 'LONG' },
  STOCKBRIDGE_STRAIGHT: { type: 'prairie', arched: false, size: 'LONG' },
  STOCKBRIDGE_STRAIGHT_XL: { type: 'prairie', arched: false, xl: true, size: 'LONG' },
  STOCKBRIDGE_ARCHED_XL: { type: 'prairie', arched: true, xl: true, size: 'LONG' },
  STOCKBRIDGE_ARCHED: { type: 'prairie', arched: true, size: 'LONG' },
  // 14x20 windows (for SH/BC short stamps - fits in 1 stamp)
  STOCKTON_SHORT: { type: 'grid', rows: 2, cols: 2, arched: false, size: 'SHORT' },
  STOCKTON_SHORT_ARCHED: { type: 'grid', rows: 2, cols: 2, arched: true, size: 'SHORT' },
  PLAIN_LONG: { type: 'plain', rows: 0, cols: 0, arched: false, size: 'LONG' },
  PLAIN_SHORT: { type: 'plain', rows: 0, cols: 0, arched: false, size: 'SHORT' },
}

function DoorPreview({
  width = 96, // inches
  height = 84, // inches
  color = 'WHITE',
  panelDesign = 'SHXL',
  windowInsert = null,
  windowPositions = [],  // Array of {section, col} for multi-stamp windows
  windowSection = 1,  // Legacy: single section (used if windowPositions empty)
  windowSize = 'long',  // 'short' or 'long' — long spans 2 standard stamps
  hasInserts = false,  // Whether decorative inserts are added
  glassColor = 'CLEAR',  // Glass color: CLEAR, ETCHED, SUPER_GREY
  windowQty = 0,  // For commercial doors
  windowPanels = null,  // Per-panel window config: { "1": { qty: 4 }, "3": { qty: 4 } }
  windowFrameColor = 'MATCH',  // 'MATCH' = darken door color, or a color ID / 'WHITE' / 'BLACK'
  doorType = 'residential',
  doorSeries = '',  // 'CRAFT' for 3-panel doors
  showDimensions = true,
  scale = 1,
  interactive = false,  // Enable click-to-place window mode
  onStampClick = null,  // Callback when stamp is clicked (section, col)
  onSectionClick = null,  // Legacy: Callback when section is clicked
  highlightStamp = null,  // {section, col} to highlight
  highlightSection = null,  // Section to highlight (for hover effect)
  onStampHover = null,  // Callback when hovering over a stamp (section, col)
  onSectionHover = null,  // Legacy: Callback when hovering over a section
}) {
  const isCommercial = doorType === 'commercial'
  // Calculate display dimensions (max 400px width for preview)
  const maxDisplayWidth = 400 * scale
  const aspectRatio = height / width
  const displayWidth = Math.min(maxDisplayWidth, 400)
  const displayHeight = displayWidth * aspectRatio

  // Helper to check if a specific stamp position has a window
  const hasWindowAtPosition = (section, col) => {
    if (windowPositions && windowPositions.length > 0) {
      return windowPositions.some(pos => pos.section === section && pos.col === col)
    }
    // Legacy: if no windowPositions, use single windowSection (all stamps in that section)
    return windowInsert && windowInsert !== 'NONE' && section === windowSection
  }

  // Check if any window exists (for rendering purposes)
  const hasAnyWindows = windowInsert && windowInsert !== 'NONE' && (
    (windowPositions && windowPositions.length > 0) || windowSection
  )

  // Calculate stamp columns for current door width using pattern's stamp type
  const isCraft = doorSeries === 'CRAFT'
  const currentPattern = PANEL_PATTERNS[panelDesign] || PANEL_PATTERNS.SHXL
  const stampColumns = getStampColumns(width, currentPattern.stampType, isCraft, panelDesign)

  // Calculate section heights
  const sectionConfig = useMemo(() => {
    // Craft series: 3 panels (28" for 7' doors, 32" for 8' doors)
    if (isCraft) {
      const sectionH = height <= 84 ? 28 : 32
      return [sectionH, sectionH, sectionH]
    }

    // Standard: determine number of sections based on height
    if (height <= 84) {
      return [21, 21, 21, 21]
    } else if (height <= 96) {
      return [24, 24, 24, 24]
    } else if (height <= 120) {
      return [24, 24, 24, 24, 24]
    } else if (height <= 144) {
      return [24, 24, 24, 24, 24, 24]
    } else if (height <= 168) {
      return [24, 24, 24, 24, 24, 24, 24]
    } else {
      return [24, 24, 24, 24, 24, 24, 24, 24]
    }
  }, [height, isCraft])

  const totalSectionHeight = sectionConfig.reduce((a, b) => a + b, 0)
  const sectionHeightScale = height / totalSectionHeight

  // Get colors
  const doorColor = COLOR_MAP[color] || COLOR_MAP.WHITE
  const isDark = ['BLACK', 'WALNUT', 'IRON_ORE', 'NEW_BROWN', 'ENGLISH_CHESTNUT'].includes(color)
  const lineColor = isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.2)'
  const shadowColor = isDark ? 'rgba(0,0,0,0.5)' : 'rgba(0,0,0,0.15)'

  // Resolved window frame color (MATCH = darkened door color)
  const resolvedFrame = resolveFrameColor(windowFrameColor, doorColor, color)

  // Render panel design
  // Render window overlays for panel types that don't natively handle stamps (flush, ribbed, UDC)
  const renderWindowOverlays = (y, w, h, padding, sectionIndex) => {
    const absoluteSection = sectionIndex + 1
    const cols = getStampColumns(width, currentPattern.stampType, isCraft, panelDesign)
    const gapX = w * 0.02
    const cellW = (w - gapX * (cols + 1)) / cols
    const cellH = h  // Full section height for single-row patterns

    const windows = []
    for (let col = 0; col < cols; col++) {
      if (hasWindowAtPosition(absoluteSection, col)) {
        const x = padding + gapX + col * (cellW + gapX)
        windows.push(
          <g key={`window-overlay-${sectionIndex}-${col}`}>
            {renderStampWindow(x, y, cellW, cellH, col)}
          </g>
        )
      }
    }
    return windows
  }

  const isAluminium = doorType === 'aluminium'

  const renderPanelDesign = (sectionIndex, sectionY, sectionHeight) => {
    const pattern = PANEL_PATTERNS[panelDesign] || PANEL_PATTERNS.FLUSH
    const padding = displayWidth * 0.02
    const panelWidth = displayWidth - padding * 2
    const panelHeight = sectionHeight - padding * 2

    // Aluminum doors: ALL sections are full-view glass
    if (isAluminium) {
      return renderAluminumSection(sectionY, sectionHeight, padding, panelWidth, sectionIndex)
    }

    // V130G full-view section: renders entire section as aluminum/glass
    if (isCommercial && windowInsert === 'V130G' && windowQty > 0) {
      const hasV130G = windowPanels
        ? !!(windowPanels[sectionIndex + 1]?.qty)
        : (sectionIndex >= ((windowSection || 1) - 1) && sectionIndex < ((windowSection || 1) - 1) + windowQty)
      if (hasV130G) {
        return renderV130GSection(sectionY, sectionHeight, padding, panelWidth)
      }
    }

    // Check if this section has commercial thermopane windows (not V130G)
    const panelNum = sectionIndex + 1  // panels are 1-indexed
    const panelWindowQty = windowPanels ? (windowPanels[panelNum]?.qty || 0) : (sectionIndex === (windowSection - 1) ? windowQty : 0)
    const hasCommercialWindows = isCommercial && windowInsert && windowInsert !== 'NONE' && windowInsert !== 'V130G' &&
        panelWindowQty > 0

    // Craft series designs: delegate to Craft-specific renderer
    if (pattern.type === 'xbrace' || pattern.type === 'raised_grid') {
      return renderCraftSection(sectionIndex, sectionY, sectionHeight, pattern)
    }

    // Render base panel design first, then overlay windows on top
    let baseElements
    switch (pattern.type) {
      case 'raised':
        baseElements = renderRaisedPanels(sectionY + padding, panelWidth, panelHeight, padding, pattern, sectionIndex)
        break
      case 'carriage':
        baseElements = renderCarriagePanels(sectionY + padding, panelWidth, panelHeight, padding, pattern, sectionIndex)
        break
      case 'ribbed':
        baseElements = renderRibbedPanels(sectionY + padding, panelWidth, panelHeight, padding, pattern)
        break
      case 'horizontal_ribbed':
        baseElements = renderHorizontalRibbedPanels(sectionY + padding, panelWidth, panelHeight, padding, pattern)
        break
      case 'flush':
      default:
        baseElements = renderFlushPanel(sectionY + padding, panelWidth, panelHeight, padding)
        break
    }

    // Overlay commercial thermopane windows on top of the panel design
    if (hasCommercialWindows) {
      const windowOverlay = renderCommercialWindows(sectionY + padding, panelWidth, panelHeight, padding, sectionIndex, panelWindowQty)
      return <>{baseElements}{windowOverlay}</>
    }

    // Overlay residential windows on top for ribbed/horizontal_ribbed/flush
    if (pattern.type !== 'raised' && pattern.type !== 'carriage') {
      const windowOverlays = renderWindowOverlays(sectionY + padding, panelWidth, panelHeight, padding, sectionIndex)
      if (windowOverlays.length > 0) {
        return <>{baseElements}{windowOverlays}</>
      }
    }

    return baseElements
  }

  // Render V130G full-view aluminum/glass section
  const renderV130GSection = (sectionY, sectionHeight, padding, panelWidth) => {
    const elements = []
    // V130G frame color matches door color: White→White, Black→Black, else→Clear Anodized (silver)
    const v130gFrameColors = {
      WHITE: { fill: '#E8E8E8', stroke: '#B0B0B0' },         // White frame
      BRIGHT_WHITE: { fill: '#E8E8E8', stroke: '#B0B0B0' },  // White frame
      BLACK: { fill: '#1a1a1a', stroke: '#000000' },          // Black frame
      STEEL_GREY: { fill: '#A0A0A0', stroke: '#787878' },    // Clear Anodized
    }
    const v130gFrame = v130gFrameColors[color] || v130gFrameColors.STEEL_GREY  // Default: Clear Ano
    const frameColor = v130gFrame.fill
    const frameStroke = v130gFrame.stroke
    const glassColors = {
      'CLEAR': '#87CEEB',
      'ETCHED': '#D3D3D3',
      'SUPER_GREY': '#3D3D3D',
    }
    const glassFill = glassColors[glassColor] || glassColors['CLEAR']

    const x = padding
    const y = sectionY
    const w = panelWidth
    const h = sectionHeight
    const framePad = 3        // outer frame border
    const mullionW = 3        // vertical mullion width

    // Calculate number of panes based on door width (roughly 1 pane per 3-4 feet)
    const widthFeet = width / 12
    let paneCount
    if (widthFeet <= 10) paneCount = 3
    else if (widthFeet <= 14) paneCount = 4
    else if (widthFeet <= 18) paneCount = 5
    else if (widthFeet <= 22) paneCount = 6
    else paneCount = 7

    // Outer aluminum frame (full section)
    elements.push(
      <rect key="v130g-frame" x={x} y={y} width={w} height={h}
        fill={frameColor} stroke={frameStroke} strokeWidth="1.5" rx="1" />
    )

    // Glass panes with mullions
    const innerX = x + framePad
    const innerY = y + framePad
    const innerW = w - framePad * 2
    const innerH = h - framePad * 2
    const totalMullionW = mullionW * (paneCount - 1)
    const paneW = (innerW - totalMullionW) / paneCount

    for (let i = 0; i < paneCount; i++) {
      const paneX = innerX + i * (paneW + mullionW)

      // Glass pane
      elements.push(
        <rect key={`v130g-glass-${i}`} x={paneX} y={innerY}
          width={paneW} height={innerH}
          fill={glassFill} stroke={frameStroke} strokeWidth="0.5" />
      )

      // Glass reflection
      elements.push(
        <rect key={`v130g-reflect-${i}`}
          x={paneX + paneW * 0.08} y={innerY + innerH * 0.08}
          width={paneW * 0.25} height={innerH * 0.4}
          fill="rgba(255,255,255,0.25)" rx="1" />
      )
    }

    return <g key="v130g-section">{elements}</g>
  }

  // Render aluminum door section (AL976, Panorama, Solalite) — full-view glass panel
  const renderAluminumSection = (sectionY, sectionHeight, padding, panelWidth, sectionIndex) => {
    const elements = []
    const isPolycarbonate = ['PANORAMA', 'SOLALITE'].includes(doorSeries)

    // Frame color based on aluminum finish
    const aluminumFrames = {
      CLEAR_ANODIZED: { fill: '#B8B8B8', stroke: '#909090', highlight: '#D0D0D0' },
      BLACK_ANODIZED: { fill: '#2A2A2A', stroke: '#111111', highlight: '#444444' },
      WHITE:          { fill: '#E8E8E8', stroke: '#C0C0C0', highlight: '#FFFFFF' },
      BRIGHT_WHITE:   { fill: '#E8E8E8', stroke: '#C0C0C0', highlight: '#FFFFFF' },
      MILL:           { fill: '#CCCCCC', stroke: '#A0A0A0', highlight: '#DDDDDD' },
    }
    const frame = aluminumFrames[color] || aluminumFrames.CLEAR_ANODIZED

    // Glazing color — glass for AL976, polycarbonate for Panorama/Solalite
    const glassLookup = isPolycarbonate ? {
      'CLEAR':        { fill: '#D8E8EC', ribStroke: 'rgba(180,200,210,0.5)', ribHighlight: 'rgba(255,255,255,0.3)' },
      'LIGHT_BRONZE': { fill: '#817F68', ribStroke: 'rgba(100,98,80,0.45)', ribHighlight: 'rgba(255,255,255,0.18)' },
      'DARK_BRONZE':  { fill: '#4C4A44', ribStroke: 'rgba(55,53,48,0.5)', ribHighlight: 'rgba(255,255,255,0.10)' },
      'WHITE_OPAL':   { fill: '#F4F4F4', ribStroke: 'rgba(210,210,210,0.45)', ribHighlight: 'rgba(255,255,255,0.4)' },
    } : {
      'CLEAR':      { fill: '#A8D8EA', reflection: 'rgba(255,255,255,0.35)' },
      'ETCHED':     { fill: '#D3D3D3', reflection: 'rgba(255,255,255,0.2)' },
      'SUPER_GREY': { fill: '#4A4A4A', reflection: 'rgba(255,255,255,0.15)' },
    }
    const glass = glassLookup[glassColor] || glassLookup['CLEAR']

    const totalSections = sectionConfig.length
    const isFirst = sectionIndex === 0
    const isLast = sectionIndex === totalSections - 1

    const x = padding
    const y = sectionY
    const w = panelWidth
    const h = sectionHeight
    const frameW = 4          // aluminum frame width (sides)
    const mullionW = 3        // vertical mullion
    const outerRailH = padding + frameW  // top/bottom of door matches side border thickness
    const innerRailH = 2      // thin rail between sections (joint line)

    // Top/bottom inset depends on whether this is an outer edge or an inner joint
    const topInset = isFirst ? outerRailH : innerRailH
    const bottomInset = isLast ? outerRailH : innerRailH

    // Outer aluminum frame
    elements.push(
      <rect key={`al-frame-${sectionIndex}`}
        x={x} y={y} width={w} height={h}
        fill={frame.fill} stroke={frame.stroke} strokeWidth="1" rx="0.5" />
    )

    // Frame highlight (top edge for 3D effect)
    if (isFirst) {
      elements.push(
        <line key={`al-highlight-${sectionIndex}`}
          x1={x + 1} y1={y + 1} x2={x + w - 1} y2={y + 1}
          stroke={frame.highlight} strokeWidth="0.5" opacity="0.6" />
      )
    }

    const innerX = x + frameW
    const innerY = y + topInset
    const innerW = w - frameW * 2
    const innerH = h - topInset - bottomInset

    if (isPolycarbonate) {
      // Panorama/Solalite: single full-width polycarbonate panel per section (no vertical stiles)
      elements.push(
        <rect key={`al-poly-${sectionIndex}`}
          x={innerX} y={innerY} width={innerW} height={innerH}
          fill={glass.fill} stroke={frame.stroke} strokeWidth="0.3" />
      )

      // Multiwall polycarbonate texture — visible horizontal channel ribs
      const ribSpacing = 1.8  // consistent spacing between ribs
      const ribCount = Math.max(3, Math.floor(innerH / ribSpacing) - 1)
      const actualSpacing = innerH / (ribCount + 1)
      for (let r = 1; r <= ribCount; r++) {
        const ry = innerY + r * actualSpacing
        // Dark rib line (channel wall shadow)
        elements.push(
          <line key={`al-rib-${sectionIndex}-${r}`}
            x1={innerX + 0.3} y1={ry}
            x2={innerX + innerW - 0.3} y2={ry}
            stroke={glass.ribStroke} strokeWidth="0.5" />
        )
        // Light highlight just below (top of next channel catches light)
        elements.push(
          <line key={`al-ribhl-${sectionIndex}-${r}`}
            x1={innerX + 0.3} y1={ry + 0.5}
            x2={innerX + innerW - 0.3} y2={ry + 0.5}
            stroke={glass.ribHighlight} strokeWidth="0.3" />
        )
      }

      // Subtle overall sheen at top of panel
      elements.push(
        <rect key={`al-sheen-${sectionIndex}`}
          x={innerX} y={innerY} width={innerW} height={innerH * 0.15}
          fill="rgba(255,255,255,0.08)" />
      )
    } else {
      // AL976: glass panes with vertical stiles (grid pattern)
      const widthFeet = width / 12
      let paneCount
      if (widthFeet <= 10) paneCount = 3
      else if (widthFeet <= 14) paneCount = 4
      else if (widthFeet <= 18) paneCount = 5
      else if (widthFeet <= 22) paneCount = 6
      else paneCount = 7

      const totalMullionW = mullionW * (paneCount - 1)
      const paneW = (innerW - totalMullionW) / paneCount

      for (let i = 0; i < paneCount; i++) {
        const paneX = innerX + i * (paneW + mullionW)

        // Glass pane
        elements.push(
          <rect key={`al-glass-${sectionIndex}-${i}`}
            x={paneX} y={innerY} width={paneW} height={innerH}
            fill={glass.fill} stroke={frame.stroke} strokeWidth="0.3" />
        )

        // Reflection highlight (diagonal)
        elements.push(
          <rect key={`al-reflect-${sectionIndex}-${i}`}
            x={paneX + paneW * 0.06} y={innerY + innerH * 0.06}
            width={paneW * 0.2} height={innerH * 0.35}
            fill={glass.reflection} rx="0.5"
            transform={`skewX(-3)`} />
        )
      }

      // Center stile accent (slightly thicker middle mullion if even pane count)
      if (paneCount % 2 === 0) {
        const centerIdx = paneCount / 2 - 1
        const centerX = innerX + centerIdx * (paneW + mullionW) + paneW
        elements.push(
          <rect key={`al-stile-${sectionIndex}`}
            x={centerX - 0.5} y={innerY} width={mullionW + 1} height={innerH}
            fill={frame.fill} stroke="none" />
        )
      }
    }

    return <g key={`al-section-${sectionIndex}`}>{elements}</g>
  }

  // Render commercial windows (multiple windows across a section)
  const renderCommercialWindows = (y, w, h, padding, sectionIdx = 0, qty = windowQty) => {
    const elements = []
    const frameColor = windowFrameColor === 'BLACK' ? '#1a1a1a' : '#FFFFFF'
    const frameStroke = windowFrameColor === 'BLACK' ? '#000' : '#888'

    // Get window dimensions in inches based on type (WidthxHeight)
    const windowSizes = {
      '24X12_THERMOPANE': { width: 24, height: 12 },
      '34X16_THERMOPANE': { width: 34, height: 16 },
      '18X8_THERMOPANE': { width: 18, height: 8 },
    }
    const windowSize = windowSizes[windowInsert] || { width: 24, height: 12 }

    // Get actual section height in inches for proper vertical scaling
    const sectionInches = sectionConfig[sectionIdx] || 24

    // Scale using the panel's actual dimensions (w maps to door width, h maps to section height)
    const hScale = w / width          // horizontal: SVG pixels per inch
    const vScale = h / sectionInches  // vertical: SVG pixels per inch (accounts for padding)

    const scaledWindowWidth = windowSize.width * hScale
    const scaledWindowHeight = windowSize.height * vScale
    const frameThickness = Math.max(2, 2.5 * hScale)

    // Calculate even spacing across the full panel width
    const totalWindowWidth = scaledWindowWidth * qty
    const spaces = qty + 1
    const spacing = (w - totalWindowWidth) / spaces

    // Render each window
    for (let i = 0; i < qty; i++) {
      const windowX = padding + spacing + i * (scaledWindowWidth + spacing)
      const windowY = y + (h - scaledWindowHeight) / 2  // vertically centered

      elements.push(
        <g key={`commercial-window-${sectionIdx}-${i}`}>
          {/* Panel-colored cutout behind window (covers panel ribs/design) */}
          <rect
            x={windowX - frameThickness - 1}
            y={windowY - frameThickness - 1}
            width={scaledWindowWidth + (frameThickness + 1) * 2}
            height={scaledWindowHeight + (frameThickness + 1) * 2}
            fill={doorColor}
            stroke="none"
          />
          {/* Window frame */}
          <rect
            x={windowX - frameThickness}
            y={windowY - frameThickness}
            width={scaledWindowWidth + frameThickness * 2}
            height={scaledWindowHeight + frameThickness * 2}
            fill={frameColor}
            stroke={frameStroke}
            strokeWidth="1.5"
            rx="1"
          />
          {/* Glass pane */}
          <rect
            x={windowX}
            y={windowY}
            width={scaledWindowWidth}
            height={scaledWindowHeight}
            fill="#87CEEB"
            stroke="#5a8fa8"
            strokeWidth="0.5"
          />
          {/* Glass reflection highlight */}
          <rect
            x={windowX + 2}
            y={windowY + 2}
            width={scaledWindowWidth * 0.25}
            height={scaledWindowHeight * 0.35}
            fill="rgba(255,255,255,0.3)"
            rx="1"
          />
        </g>
      )
    }

    return elements
  }

  // Render a window within a single stamp area
  const renderStampWindow = (x, y, stampW, stampH, colIndex) => {
    const windowShape = WINDOW_SHAPES[windowInsert] || WINDOW_SHAPES.STOCKTON_STANDARD
    const frameColor = resolvedFrame.stroke

    // Glass color mapping
    const glassColorMap = {
      'CLEAR': '#87CEEB',      // Light blue (clear glass)
      'ETCHED': '#D3D3D3',     // Light grey (frosted)
      'SUPER_GREY': '#3D3D3D', // Dark grey/almost black
    }
    const glassFill = glassColorMap[glassColor] || glassColorMap.CLEAR

    // Calculate window size to fit within stamp with padding
    const windowPadding = Math.min(stampW, stampH) * 0.08
    const windowWidth = stampW - windowPadding * 2
    const windowHeight = stampH - windowPadding * 2
    const windowX = x + windowPadding
    const windowY = y + windowPadding

    const elements = []

    // Window frame with glass
    elements.push(
      <rect
        key={`window-frame-${colIndex}`}
        x={windowX}
        y={windowY}
        width={windowWidth}
        height={windowHeight}
        fill={glassFill}
        stroke={frameColor}
        strokeWidth="2"
        rx="2"
        ry="2"
      />
    )

    // Only render insert pattern if hasInserts is true
    // Without inserts, window is just plain glass
    if (!hasInserts) {
      // Plain glass - just add reflection and return
      elements.push(
        <rect
          key={`reflection-${colIndex}`}
          x={windowX + 3}
          y={windowY + 3}
          width={windowWidth * 0.25}
          height={windowHeight * 0.35}
          fill="url(#glassReflection)"
          opacity="0.3"
        />
      )
      return elements
    }

    // Render insert pattern (decorative frame grid)
    if (windowShape.type === 'grid') {
      const { rows, cols: gridCols } = windowShape
      const cellW = windowWidth / gridCols
      const cellH = windowHeight / rows

      // Vertical lines
      for (let i = 1; i < gridCols; i++) {
        elements.push(
          <line
            key={`wv-${colIndex}-${i}`}
            x1={windowX + cellW * i}
            y1={windowY}
            x2={windowX + cellW * i}
            y2={windowY + windowHeight}
            stroke={frameColor}
            strokeWidth="1.5"
          />
        )
      }
      // Horizontal lines
      for (let i = 1; i < rows; i++) {
        elements.push(
          <line
            key={`wh-${colIndex}-${i}`}
            x1={windowX}
            y1={windowY + cellH * i}
            x2={windowX + windowWidth}
            y2={windowY + cellH * i}
            stroke={frameColor}
            strokeWidth="1.5"
          />
        )
      }

      // Arched top
      if (windowShape.arched) {
        const archHeight = windowHeight * 0.15
        elements.push(
          <path
            key={`arch-${colIndex}`}
            d={`M ${windowX} ${windowY + archHeight}
                Q ${windowX + windowWidth / 2} ${windowY - archHeight * 0.5}
                  ${windowX + windowWidth} ${windowY + archHeight}`}
            fill="none"
            stroke={frameColor}
            strokeWidth="2"
          />
        )
      }
    } else if (windowShape.type === 'prairie') {
      // Prairie style window with border pattern
      const borderSize = windowWidth * 0.12
      elements.push(
        <rect
          key={`prairie-inner-${colIndex}`}
          x={windowX + borderSize}
          y={windowY + borderSize}
          width={windowWidth - borderSize * 2}
          height={windowHeight - borderSize * 2}
          fill="none"
          stroke={frameColor}
          strokeWidth="1.5"
        />
      )
      // Corner accents
      const corners = [
        [windowX, windowY],
        [windowX + windowWidth - borderSize, windowY],
        [windowX, windowY + windowHeight - borderSize],
        [windowX + windowWidth - borderSize, windowY + windowHeight - borderSize],
      ]
      corners.forEach(([cx, cy], i) => {
        elements.push(
          <rect
            key={`corner-${colIndex}-${i}`}
            x={cx}
            y={cy}
            width={borderSize}
            height={borderSize}
            fill="none"
            stroke={frameColor}
            strokeWidth="1"
          />
        )
      })
    }

    // Glass reflection effect
    elements.push(
      <rect
        key={`reflection-${colIndex}`}
        x={windowX + 3}
        y={windowY + 3}
        width={windowWidth * 0.25}
        height={windowHeight * 0.35}
        fill="url(#glassReflection)"
        opacity="0.3"
      />
    )

    return elements
  }

  const renderRaisedPanels = (y, w, h, padding, pattern, sectionIndex) => {
    const { rows } = pattern
    // Calculate columns dynamically based on door width and stamp type
    const cols = pattern.cols === 'dynamic' ? getStampColumns(width, pattern.stampType, isCraft, panelDesign) : pattern.cols
    // Gap between stamps
    const gapX = w * 0.012
    const gapY = h * 0.03
    // Calculate cell dimensions accounting for gaps
    const cellW = (w - gapX * (cols + 1)) / cols
    const cellH = (h - gapY * (rows + 1)) / rows

    // Long window on SH/BC (standard stamp): each window spans 2 adjacent stamp columns
    const isLongOnStandard = windowSize === 'long' && pattern.stampType === 'standard'

    const panels = []
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const x = padding + gapX + col * (cellW + gapX)
        const cellY = y + gapY + row * (cellH + gapY)
        const stampKey = `stamp-${sectionIndex}-${row}-${col}`

        const absoluteSection = sectionIndex + 1  // 1-based section

        // In long mode, odd cols consumed by the even col's spanning window — skip them
        if (isLongOnStandard && col % 2 === 1 && hasWindowAtPosition(absoluteSection, col - 1)) {
          continue
        }

        if (hasWindowAtPosition(absoluteSection, col)) {
          // Long mode: window spans this cell + the next (2 stamps wide)
          const windowW = isLongOnStandard ? cellW * 2 + gapX : cellW
          panels.push(
            <g key={stampKey}>
              {renderStampWindow(x, cellY, windowW, cellH, col)}
            </g>
          )
          continue
        }

        // Outer border inset from cell edge
        const outerInset = Math.min(cellW, cellH) * 0.05
        // Inner raised panel inset from outer border
        const innerInset = Math.min(cellW, cellH) * 0.12

        // For long mode: normalize click col to the even anchor of this pair
        const clickCol = isLongOnStandard ? Math.floor(col / 2) * 2 : col
        // For long mode: highlight entire pair when either stamp in the pair is hovered
        const pairStart = isLongOnStandard ? Math.floor(col / 2) * 2 : col
        const isHovered = interactive && highlightStamp &&
          highlightStamp.section === absoluteSection &&
          (isLongOnStandard
            ? Math.floor(highlightStamp.col / 2) * 2 === pairStart
            : highlightStamp.col === col)

        panels.push(
          <g
            key={stampKey}
            style={interactive ? { cursor: 'pointer' } : {}}
            onClick={interactive && onStampClick ? () => onStampClick(absoluteSection, clickCol) : undefined}
            onMouseEnter={interactive && onStampHover ? () => onStampHover(absoluteSection, col) : undefined}
            onMouseLeave={interactive && onStampHover ? () => onStampHover(null) : undefined}
          >
            {/* Highlight overlay for interactive mode — spans 2 cells in long mode */}
            {isHovered && col % 2 === pairStart % 2 && (
              <rect
                x={x}
                y={cellY}
                width={isLongOnStandard ? cellW * 2 + gapX : cellW}
                height={cellH}
                fill="rgba(59, 130, 246, 0.2)"
                stroke="rgba(59, 130, 246, 0.8)"
                strokeWidth="2"
                strokeDasharray="4,2"
                rx="2"
              />
            )}
            {/* Outer rectangle border */}
            <rect
              x={x + outerInset}
              y={cellY + outerInset}
              width={cellW - outerInset * 2}
              height={cellH - outerInset * 2}
              fill="none"
              stroke={lineColor}
              strokeWidth="1.5"
            />
            {/* Inner raised rectangle */}
            <rect
              x={x + outerInset + innerInset}
              y={cellY + outerInset + innerInset}
              width={cellW - (outerInset + innerInset) * 2}
              height={cellH - (outerInset + innerInset) * 2}
              fill="none"
              stroke={lineColor}
              strokeWidth="1"
            />
            {/* 3D effect - shadow on bottom/right of inner panel */}
            <line
              x1={x + outerInset + innerInset}
              y1={cellY + cellH - outerInset - innerInset}
              x2={x + cellW - outerInset - innerInset}
              y2={cellY + cellH - outerInset - innerInset}
              stroke={shadowColor}
              strokeWidth="2"
            />
            <line
              x1={x + cellW - outerInset - innerInset}
              y1={cellY + outerInset + innerInset}
              x2={x + cellW - outerInset - innerInset}
              y2={cellY + cellH - outerInset - innerInset}
              stroke={shadowColor}
              strokeWidth="2"
            />
            {/* 3D effect - highlight on top/left of inner panel */}
            <line
              x1={x + outerInset + innerInset}
              y1={cellY + outerInset + innerInset}
              x2={x + cellW - outerInset - innerInset}
              y2={cellY + outerInset + innerInset}
              stroke={isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.7)'}
              strokeWidth="1"
            />
            <line
              x1={x + outerInset + innerInset}
              y1={cellY + outerInset + innerInset}
              x2={x + outerInset + innerInset}
              y2={cellY + cellH - outerInset - innerInset}
              stroke={isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.7)'}
              strokeWidth="1"
            />
          </g>
        )
      }
    }
    return panels
  }

  const renderCarriagePanels = (y, w, h, padding, pattern, sectionIndex) => {
    const { rows } = pattern
    // Calculate columns dynamically based on door width and stamp type for Bronte Creek styles
    const cols = pattern.cols === 'dynamic' ? getStampColumns(width, pattern.stampType, isCraft, panelDesign) : pattern.cols
    // Gap between stamps
    const gapX = w * 0.012
    const gapY = h * 0.03
    const cellW = (w - gapX * (cols + 1)) / cols
    const cellH = (h - gapY * (rows + 1)) / rows

    // Long window on BC (standard stamp): each window spans 2 adjacent stamp columns
    const isLongOnStandard = windowSize === 'long' && pattern.stampType === 'standard'

    const panels = []
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const x = padding + gapX + col * (cellW + gapX)
        const cellY = y + gapY + row * (cellH + gapY)
        const stampKey = `carriage-${sectionIndex}-${row}-${col}`

        const absoluteSection = sectionIndex + 1  // 1-based section

        // In long mode, odd cols consumed by the even col's spanning window — skip them
        if (isLongOnStandard && col % 2 === 1 && hasWindowAtPosition(absoluteSection, col - 1)) {
          continue
        }

        if (hasWindowAtPosition(absoluteSection, col)) {
          // Long mode: window spans this cell + the next (2 stamps wide)
          const windowW = isLongOnStandard ? cellW * 2 + gapX : cellW
          panels.push(
            <g key={stampKey}>
              {renderStampWindow(x, cellY, windowW, cellH, col)}
            </g>
          )
          continue
        }

        // Outer border inset
        const outerInset = Math.min(cellW, cellH) * 0.05
        // Inner frame inset
        const innerInset = Math.min(cellW, cellH) * 0.12
        const cornerRadius = Math.min(cellW, cellH) * 0.03

        // For long mode: normalize click col to the even anchor of this pair
        const clickCol = isLongOnStandard ? Math.floor(col / 2) * 2 : col
        // For long mode: highlight entire pair when either stamp in the pair is hovered
        const pairStart = isLongOnStandard ? Math.floor(col / 2) * 2 : col
        const isHovered = interactive && highlightStamp &&
          highlightStamp.section === absoluteSection &&
          (isLongOnStandard
            ? Math.floor(highlightStamp.col / 2) * 2 === pairStart
            : highlightStamp.col === col)

        panels.push(
          <g
            key={stampKey}
            style={interactive ? { cursor: 'pointer' } : {}}
            onClick={interactive && onStampClick ? () => onStampClick(absoluteSection, clickCol) : undefined}
            onMouseEnter={interactive && onStampHover ? () => onStampHover(absoluteSection, col) : undefined}
            onMouseLeave={interactive && onStampHover ? () => onStampHover(null) : undefined}
          >
            {/* Highlight overlay for interactive mode — spans 2 cells in long mode */}
            {isHovered && col % 2 === pairStart % 2 && (
              <rect
                x={x}
                y={cellY}
                width={isLongOnStandard ? cellW * 2 + gapX : cellW}
                height={cellH}
                fill="rgba(59, 130, 246, 0.2)"
                stroke="rgba(59, 130, 246, 0.8)"
                strokeWidth="2"
                strokeDasharray="4,2"
                rx="2"
              />
            )}
            {/* Outer rectangle border */}
            <rect
              x={x + outerInset}
              y={cellY + outerInset}
              width={cellW - outerInset * 2}
              height={cellH - outerInset * 2}
              rx={cornerRadius}
              ry={cornerRadius}
              fill="none"
              stroke={lineColor}
              strokeWidth="1.5"
            />
            {/* Inner decorative frame */}
            <rect
              x={x + outerInset + innerInset}
              y={cellY + outerInset + innerInset}
              width={cellW - (outerInset + innerInset) * 2}
              height={cellH - (outerInset + innerInset) * 2}
              rx={cornerRadius * 0.5}
              ry={cornerRadius * 0.5}
              fill="none"
              stroke={lineColor}
              strokeWidth="1"
            />
            {/* Vertical board groove lines for Bronte Creek carriage style */}
            {(pattern.style === 'bronte') && (() => {
              const innerX = x + outerInset + innerInset
              const innerY2 = cellY + outerInset + innerInset
              const innerW = cellW - (outerInset + innerInset) * 2
              const innerH = cellH - (outerInset + innerInset) * 2
              // Grooves proportional to actual stamp width (works for both Kanata and Craft)
              const numGrooves = Math.max(4, Math.round(innerW / 12))
              const grooveSpacing = innerW / (numGrooves + 1)
              const grooves = []
              for (let g = 1; g <= numGrooves; g++) {
                grooves.push(
                  <line
                    key={`groove-${sectionIndex}-${row}-${col}-${g}`}
                    x1={innerX + grooveSpacing * g}
                    y1={innerY2}
                    x2={innerX + grooveSpacing * g}
                    y2={innerY2 + innerH}
                    stroke={lineColor}
                    strokeWidth="0.75"
                  />
                )
              }
              return grooves
            })()}
            {/* Single vertical divider for other carriage styles */}
            {(pattern.style !== 'bronte' && (pattern.style === 'carriage' || pattern.style === 'muskoka' || pattern.style === 'denison' || pattern.style === 'granville')) && (
              <line
                x1={x + cellW * 0.5}
                y1={cellY + outerInset + innerInset}
                x2={x + cellW * 0.5}
                y2={cellY + cellH - outerInset - innerInset}
                stroke={lineColor}
                strokeWidth="1"
              />
            )}
            {/* Horizontal divider for some carriage styles */}
            {(pattern.style === 'muskoka' || pattern.style === 'denison') && (
              <line
                x1={x + outerInset + innerInset}
                y1={cellY + cellH * 0.5}
                x2={x + cellW - outerInset - innerInset}
                y2={cellY + cellH * 0.5}
                stroke={lineColor}
                strokeWidth="1"
              />
            )}
            {/* 3D shadow effect */}
            <line
              x1={x + outerInset + innerInset}
              y1={cellY + cellH - outerInset - innerInset}
              x2={x + cellW - outerInset - innerInset}
              y2={cellY + cellH - outerInset - innerInset}
              stroke={shadowColor}
              strokeWidth="1.5"
            />
            <line
              x1={x + cellW - outerInset - innerInset}
              y1={cellY + outerInset + innerInset}
              x2={x + cellW - outerInset - innerInset}
              y2={cellY + cellH - outerInset - innerInset}
              stroke={shadowColor}
              strokeWidth="1.5"
            />
          </g>
        )
      }
    }
    return panels
  }

  const renderRibbedPanels = (y, w, h, padding, pattern) => {
    const { ribs } = pattern
    const ribSpacing = w / (ribs + 1)
    const lines = []

    for (let i = 1; i <= ribs; i++) {
      const x = padding + ribSpacing * i
      lines.push(
        <g key={`rib-${i}`}>
          <line
            x1={x - 1}
            y1={y}
            x2={x - 1}
            y2={y + h}
            stroke={shadowColor}
            strokeWidth="2"
          />
          <line
            x1={x}
            y1={y}
            x2={x}
            y2={y + h}
            stroke={isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.6)'}
            strokeWidth="1"
          />
        </g>
      )
    }
    return lines
  }

  // Render horizontal ribbed panels (for UDC commercial and Trafalgar)
  // y and h already include padding offset - use full section edges for even spacing
  const renderHorizontalRibbedPanels = (y, w, h, padding, pattern) => {
    const { ribs } = pattern
    // Space ribs evenly from section edges: equal gap at top, between, and bottom
    const sectionTop = y - padding
    const sectionH = h + padding * 2
    const ribSpacing = sectionH / (ribs + 1)
    const lines = []

    for (let i = 1; i <= ribs; i++) {
      const lineY = sectionTop + ribSpacing * i
      lines.push(
        <g key={`h-rib-${i}`}>
          <line
            x1={0}
            y1={lineY - 0.5}
            x2={displayWidth}
            y2={lineY - 0.5}
            stroke={shadowColor}
            strokeWidth="1"
          />
          <line
            x1={0}
            y1={lineY + 0.5}
            x2={displayWidth}
            y2={lineY + 0.5}
            stroke={isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.6)'}
            strokeWidth="0.5"
          />
        </g>
      )
    }
    return lines
  }

  const renderFlushPanel = (y, w, h, padding) => {
    return (
      <rect
        x={padding}
        y={y}
        width={w}
        height={h}
        fill={doorColor}
      />
    )
  }

  // Get Craft window count based on door width
  const getCraftWindowCount = (widthInches) => {
    const widthFeet = widthInches / 12
    if (widthFeet <= 9) return 2
    if (widthFeet <= 12) return 3
    return 4 // 16'
  }

  // Render Craft series section layout
  // Section 0 (top): flush panel + windows aligned to stamp columns below
  // Sections 1-2: each section = ONE ROW of stamps (together they form the full design)
  //   Muskoka: half-X per section (∧ on section 1, ∨ on section 2 → full X across both)
  //   Denison: 3 vertical raised rectangles per stamp per section
  //   Granville: 4 vertical raised rectangles per stamp per section
  const renderCraftSection = (sectionIndex, sectionY, sectionHeight, pattern) => {
    const padding = displayWidth * 0.02
    const panelWidth = displayWidth - padding * 2
    const panelHeight = sectionHeight - padding * 2
    const stampCount = getStampColumns(width, 'long', true)

    // Shared stamp cell layout — used for both windows and stamps
    const gapX = panelWidth * 0.015
    const cellW = (panelWidth - gapX * (stampCount + 1)) / stampCount

    // Section 0 (top): flush panel with windows aligned to stamps
    if (sectionIndex === 0) {
      const elements = []
      // Flush background
      elements.push(
        <rect key="craft-top-flush"
          x={padding} y={sectionY + padding}
          width={panelWidth} height={panelHeight}
          fill={doorColor} />
      )
      // Windows: one per stamp column, aligned to stamp positions
      const windowInset = panelHeight * 0.1
      const windowH = panelHeight - windowInset * 2
      const windowGapInner = cellW * 0.06  // small inset within stamp column

      for (let i = 0; i < stampCount; i++) {
        const wx = padding + gapX + i * (cellW + gapX) + windowGapInner
        const wy = sectionY + padding + windowInset
        const windowW = cellW - windowGapInner * 2
        const frameW = 2.5
        const dividerColor = resolvedFrame.stroke
        // Window frame
        elements.push(
          <rect key={`craft-win-frame-${i}`}
            x={wx - frameW} y={wy - frameW}
            width={windowW + frameW * 2} height={windowH + frameW * 2}
            fill={resolvedFrame.fill}
            stroke={resolvedFrame.stroke}
            strokeWidth="1" rx="1" />
        )
        // Glass
        elements.push(
          <rect key={`craft-win-glass-${i}`}
            x={wx} y={wy} width={windowW} height={windowH}
            fill="#87CEEB" stroke="#666" strokeWidth="0.5" />
        )
        // Window pane dividers: 1 horizontal + 2 vertical = 3×2 grid
        elements.push(
          <line key={`craft-win-hdiv-${i}`}
            x1={wx} y1={wy + windowH / 2}
            x2={wx + windowW} y2={wy + windowH / 2}
            stroke={dividerColor} strokeWidth="1.5" />
        )
        for (let v = 1; v <= 2; v++) {
          elements.push(
            <line key={`craft-win-vdiv-${i}-${v}`}
              x1={wx + (windowW * v) / 3} y1={wy}
              x2={wx + (windowW * v) / 3} y2={wy + windowH}
              stroke={dividerColor} strokeWidth="1.5" />
          )
        }
        // Reflection
        elements.push(
          <rect key={`craft-win-refl-${i}`}
            x={wx + 3} y={wy + 3}
            width={windowW * 0.18} height={windowH * 0.22}
            fill="url(#glassReflection)" opacity="0.3" />
        )
      }
      return elements
    }

    // Sections 1-2: stamp design (one row per section)
    const cellH = panelHeight
    const cellY = sectionY + padding
    // Recessed area fill — slightly darker than door surface
    const recessFill = isDark ? 'rgba(0,0,0,0.15)' : 'rgba(0,0,0,0.06)'

    const panels = []
    for (let col = 0; col < stampCount; col++) {
      const x = padding + gapX + col * (cellW + gapX)
      const cellKey = `craft-${sectionIndex}-${col}`

      if (pattern.type === 'xbrace') {
        // Muskoka: Stamped steel X-brace — recessed triangles, surface-level X bands
        // Triangles extend to full cell edges. No outer border — X merges with panel surface.
        const cx = x + cellW / 2
        const bw = Math.max(6, Math.min(cellW, cellH) * 0.09)
        const hw = bw / 2
        const diagLen = Math.sqrt((cellW / 2) ** 2 + cellH ** 2)

        // Offsets for triangle vertices along cell edges
        const offH = hw * diagLen / cellH         // horizontal offset along top/bottom edges
        const offV = 2 * hw * diagLen / cellW      // vertical offset along side edges & apex

        let triPaths
        if (sectionIndex === 1) {
          // ∧ shape: arms from top corners to bottom center
          // Top center triangle
          const t1 = `M ${x + offH},${cellY} L ${x + cellW - offH},${cellY} L ${cx},${cellY + cellH - offV} Z`
          // Bottom-left triangle
          const t2 = `M ${x},${cellY + offV} L ${x},${cellY + cellH} L ${cx - offH},${cellY + cellH} Z`
          // Bottom-right triangle
          const t3 = `M ${x + cellW},${cellY + offV} L ${x + cellW},${cellY + cellH} L ${cx + offH},${cellY + cellH} Z`
          triPaths = [t1, t2, t3]
        } else {
          // ∨ shape: arms from bottom corners to top center
          // Bottom center triangle
          const t1 = `M ${x + offH},${cellY + cellH} L ${x + cellW - offH},${cellY + cellH} L ${cx},${cellY + offV} Z`
          // Top-left triangle
          const t2 = `M ${x},${cellY + cellH - offV} L ${x},${cellY} L ${cx - offH},${cellY} Z`
          // Top-right triangle
          const t3 = `M ${x + cellW},${cellY + cellH - offV} L ${x + cellW},${cellY} L ${cx + offH},${cellY} Z`
          triPaths = [t1, t2, t3]
        }

        const deepRecess = isDark ? 'rgba(0,0,0,0.25)' : 'rgba(0,0,0,0.12)'
        panels.push(
          <g key={cellKey}>
            {triPaths.map((d, ti) => (
              <path key={`${cellKey}-tri-${ti}`} d={d}
                fill={deepRecess} stroke={lineColor} strokeWidth="1.5" />
            ))}
          </g>
        )
      } else if (pattern.type === 'raised_grid') {
        // Denison: 3 vertical recessed rectangles per stamp
        // Granville: 4 vertical recessed rectangles per stamp
        // Very subtle recess — just thin lines with minimal depth
        const gridCols = pattern.style === 'granville' ? 4 : 3
        const inset = Math.min(cellW, cellH) * 0.04
        const ix = x + inset
        const iy = cellY + inset
        const iw = cellW - inset * 2
        const ih = cellH - inset * 2
        const gap = iw * 0.04
        const subW = (iw - gap * (gridCols + 1)) / gridCols
        const subH = ih - gap * 2

        const els = []
        // Outer stamp border — simple thin line
        els.push(
          <rect key={`${cellKey}-border`} x={ix} y={iy} width={iw} height={ih}
            fill="none" stroke={lineColor} strokeWidth="1.5" />
        )

        for (let c = 0; c < gridCols; c++) {
          const sx = ix + gap + c * (subW + gap)
          const sy = iy + gap
          // Recessed rectangle fill
          els.push(
            <rect key={`${cellKey}-fill-${c}`} x={sx} y={sy} width={subW} height={subH}
              fill={recessFill} stroke="none" />
          )
          // Rectangle border
          els.push(
            <rect key={`${cellKey}-rect-${c}`} x={sx} y={sy} width={subW} height={subH}
              fill="none" stroke={lineColor} strokeWidth="1" />
          )
        }
        panels.push(<g key={cellKey}>{els}</g>)
      }
    }
    return panels
  }

  const renderWindowSection = (y, w, h, padding) => {
    const windowShape = WINDOW_SHAPES[windowInsert] || WINDOW_SHAPES.STOCKTON_STANDARD
    const pattern = PANEL_PATTERNS[panelDesign] || PANEL_PATTERNS.SHXL
    const frameColor = resolvedFrame.stroke

    // Determine window size based on pattern type
    // SHXL/BCXL (1 row): 14x40 window fits in 1 stamp
    // SH/BC (2 rows): 14x20 window fits in 1 stamp, 14x40 spans 2 stamps
    const isLongStamp = pattern.rows === 1  // SHXL, BCXL have 1 row
    const windowSizeType = windowShape.size || 'LONG'
    const windowSizeInches = WINDOW_SIZES[windowSizeType] || WINDOW_SIZES.LONG

    // Calculate display scale
    const scaleRatio = displayWidth / width

    // Calculate window dimensions in display units
    const windowWidthDisplay = windowSizeInches.width * scaleRatio
    const windowHeightDisplay = windowSizeInches.height * scaleRatio

    // For short stamp patterns (SH/BC) with long windows (14x40), window spans 2 stamp columns
    const cols = pattern.cols === 'dynamic' ? getStampColumns(width, pattern.stampType, isCraft, panelDesign) : pattern.cols
    const gapX = w * 0.02
    const stampWidth = (w - gapX * (cols + 1)) / cols

    // Calculate how many stamps this window covers
    let stampsSpanned = 1
    if (!isLongStamp && windowSizeType === 'LONG') {
      // 14x40 window on SH/BC covers 2 short stamps horizontally
      stampsSpanned = 2
    }

    // Calculate window position - center in the stamp area(s)
    const totalStampArea = stampWidth * stampsSpanned + gapX * (stampsSpanned - 1)
    const windowX = padding + gapX + (totalStampArea - windowWidthDisplay) / 2
    const windowY = y + (h - windowHeightDisplay) / 2

    const elements = []

    // Window frame
    elements.push(
      <rect
        key="window-frame"
        x={windowX}
        y={windowY}
        width={windowWidthDisplay}
        height={windowHeightDisplay}
        fill="#87CEEB"
        stroke={frameColor}
        strokeWidth="3"
        rx="2"
        ry="2"
      />
    )

    // Use calculated dimensions for grid
    const windowWidth = windowWidthDisplay
    const windowHeight = windowHeightDisplay

    // Window grid
    if (windowShape.type === 'grid') {
      const { rows, cols: gridCols } = windowShape
      const cellW = windowWidth / gridCols
      const cellH = windowHeight / rows

      // Vertical lines
      for (let i = 1; i < gridCols; i++) {
        elements.push(
          <line
            key={`wv-${i}`}
            x1={windowX + cellW * i}
            y1={windowY}
            x2={windowX + cellW * i}
            y2={windowY + windowHeight}
            stroke={frameColor}
            strokeWidth="2"
          />
        )
      }
      // Horizontal lines
      for (let i = 1; i < rows; i++) {
        elements.push(
          <line
            key={`wh-${i}`}
            x1={windowX}
            y1={windowY + cellH * i}
            x2={windowX + windowWidth}
            y2={windowY + cellH * i}
            stroke={frameColor}
            strokeWidth="2"
          />
        )
      }

      // Arched top
      if (windowShape.arched) {
        elements.push(
          <path
            key="arch"
            d={`M ${windowX} ${windowY + 10}
                Q ${windowX + windowWidth / 2} ${windowY - 15}
                  ${windowX + windowWidth} ${windowY + 10}`}
            fill="none"
            stroke={frameColor}
            strokeWidth="3"
          />
        )
      }
    } else if (windowShape.type === 'prairie') {
      // Prairie style window with border pattern
      const borderSize = windowWidth * 0.15
      elements.push(
        <rect
          key="prairie-inner"
          x={windowX + borderSize}
          y={windowY + borderSize}
          width={windowWidth - borderSize * 2}
          height={windowHeight - borderSize * 2}
          fill="none"
          stroke={frameColor}
          strokeWidth="2"
        />
      )
      // Corner accents
      const corners = [
        [windowX, windowY],
        [windowX + windowWidth - borderSize, windowY],
        [windowX, windowY + windowHeight - borderSize],
        [windowX + windowWidth - borderSize, windowY + windowHeight - borderSize],
      ]
      corners.forEach(([cx, cy], i) => {
        elements.push(
          <rect
            key={`corner-${i}`}
            x={cx}
            y={cy}
            width={borderSize}
            height={borderSize}
            fill="none"
            stroke={frameColor}
            strokeWidth="1"
          />
        )
      })
    }

    // Glass reflection effect
    elements.push(
      <rect
        key="reflection"
        x={windowX + 5}
        y={windowY + 5}
        width={windowWidth * 0.3}
        height={windowHeight * 0.4}
        fill="url(#glassReflection)"
        opacity="0.3"
      />
    )

    return elements
  }

  // Render dimension annotations
  const renderDimensions = () => {
    if (!showDimensions) return null

    const widthFt = Math.floor(width / 12)
    const widthIn = width % 12
    const heightFt = Math.floor(height / 12)
    const heightIn = height % 12

    const widthLabel = widthIn > 0 ? `${widthFt}'-${widthIn}"` : `${widthFt}'-0"`
    const heightLabel = heightIn > 0 ? `${heightFt}'-${heightIn}"` : `${heightFt}'-0"`

    return (
      <g className="dimensions" fontFamily="Arial, sans-serif" fontSize="12" fill="#333">
        {/* Width dimension */}
        <g transform={`translate(0, ${displayHeight + 25})`}>
          <line x1="0" y1="0" x2={displayWidth} y2="0" stroke="#666" strokeWidth="1" />
          <line x1="0" y1="-5" x2="0" y2="5" stroke="#666" strokeWidth="1" />
          <line x1={displayWidth} y1="-5" x2={displayWidth} y2="5" stroke="#666" strokeWidth="1" />
          <text x={displayWidth / 2} y="15" textAnchor="middle" fontWeight="bold">{widthLabel}</text>
        </g>

        {/* Height dimension */}
        <g transform={`translate(${displayWidth + 15}, 0)`}>
          <line x1="0" y1="0" x2="0" y2={displayHeight} stroke="#666" strokeWidth="1" />
          <line x1="-5" y1="0" x2="5" y2="0" stroke="#666" strokeWidth="1" />
          <line x1="-5" y1={displayHeight} x2="5" y2={displayHeight} stroke="#666" strokeWidth="1" />
          <text
            x="15"
            y={displayHeight / 2}
            textAnchor="middle"
            fontWeight="bold"
            transform={`rotate(90, 15, ${displayHeight / 2})`}
          >
            {heightLabel}
          </text>
        </g>
      </g>
    )
  }

  // Calculate section positions
  let currentY = 0
  const sections = sectionConfig.map((sectionHeight, index) => {
    const scaledHeight = (sectionHeight * sectionHeightScale / height) * displayHeight
    const sectionY = currentY
    currentY += scaledHeight

    return {
      index,
      y: sectionY,
      height: scaledHeight,
      originalHeight: sectionHeight
    }
  })

  return (
    <div className="door-preview" style={{ display: 'inline-block' }}>
      <svg
        width={displayWidth + (showDimensions ? 50 : 0)}
        height={displayHeight + (showDimensions ? 45 : 0)}
        viewBox={`0 0 ${displayWidth + (showDimensions ? 50 : 0)} ${displayHeight + (showDimensions ? 45 : 0)}`}
      >
        <defs>
          {/* Glass reflection gradient */}
          <linearGradient id="glassReflection" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="white" stopOpacity="0.6" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </linearGradient>

          {/* Door shadow */}
          <filter id="doorShadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="3" dy="3" stdDeviation="4" floodOpacity="0.3"/>
          </filter>

          {/* Woodgrain pattern */}
          {isWoodgrain(color) && WOODGRAIN_COLORS[color] && (
            <pattern id="woodgrainPattern" patternUnits="userSpaceOnUse" width="100" height="8">
              <rect width="100" height="8" fill={WOODGRAIN_COLORS[color].base} />
              <path
                d={`M0,2 Q25,0 50,2 T100,2`}
                stroke={WOODGRAIN_COLORS[color].dark}
                strokeWidth="0.5"
                fill="none"
                opacity="0.6"
              />
              <path
                d={`M0,5 Q30,3 60,5 T100,5`}
                stroke={WOODGRAIN_COLORS[color].light}
                strokeWidth="0.3"
                fill="none"
                opacity="0.4"
              />
              <path
                d={`M0,7 Q20,6 40,7 T80,6.5 T100,7`}
                stroke={WOODGRAIN_COLORS[color].dark}
                strokeWidth="0.4"
                fill="none"
                opacity="0.5"
              />
            </pattern>
          )}
        </defs>

        {/* Door background with shadow */}
        <rect
          x="0"
          y="0"
          width={displayWidth}
          height={displayHeight}
          fill={isWoodgrain(color) ? 'url(#woodgrainPattern)' : doorColor}
          stroke="#333"
          strokeWidth="2"
          filter="url(#doorShadow)"
        />

        {/* Render each section */}
        {sections.map((section) => (
          <g key={`section-${section.index}`}>
            {/* Section number label for interactive mode */}
            {interactive && (
              <text
                x={displayWidth - 12}
                y={section.y + 14}
                fontSize="10"
                fill="#999"
                fontWeight="normal"
                textAnchor="middle"
              >
                {section.index + 1}
              </text>
            )}
            {/* Section divider line */}
            {section.index > 0 && (
              <line
                x1="0"
                y1={section.y}
                x2={displayWidth}
                y2={section.y}
                stroke={lineColor}
                strokeWidth="2"
              />
            )}
            {/* Panel design - stamps handle their own interaction */}
            {renderPanelDesign(section.index, section.y, section.height)}
          </g>
        ))}

        {/* Door frame border */}
        <rect
          x="0"
          y="0"
          width={displayWidth}
          height={displayHeight}
          fill="none"
          stroke="#333"
          strokeWidth="3"
        />

        {/* Dimensions */}
        {renderDimensions()}
      </svg>
    </div>
  )
}

export default DoorPreview
