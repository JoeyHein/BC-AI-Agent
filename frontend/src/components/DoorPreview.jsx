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

const getStampColumns = (widthInches) => {
  // Calculate how many 42" stamps fit with reasonable spacing
  // Refer to Upwardor stamp layout PDFs for exact values per width
  const widthFeet = widthInches / 12

  // Exact mappings from Upwardor layout documents
  if (widthFeet <= 8) return 3
  if (widthFeet <= 9) return 3
  if (widthFeet <= 10) return 3
  if (widthFeet <= 11) return 3
  if (widthFeet <= 12) return 3  // 12' = 144", fits 3 stamps (3x42=126") with spacing
  if (widthFeet <= 13) return 4
  if (widthFeet <= 14) return 4
  if (widthFeet <= 15) return 4
  if (widthFeet <= 16) return 4  // 16' = 192", fits 4 stamps (4x42=168") with spacing
  if (widthFeet <= 17) return 5
  if (widthFeet <= 18) return 5
  if (widthFeet <= 19) return 5
  if (widthFeet <= 20) return 6  // 20' = 240", fits 6 stamps (6x42=252") tight
  return 6
}

const PANEL_PATTERNS = {
  // Sheridan XL - Long raised panel (1 row, columns based on width)
  SHXL: {
    type: 'raised',
    rows: 1,
    cols: 'dynamic', // Will be calculated based on door width
    style: 'sheridan',
    description: 'Sheridan XL - Long Raised Panel'
  },
  // Sheridan - Short raised panel (2 rows, columns based on width)
  SH: {
    type: 'raised',
    rows: 2,
    cols: 'dynamic',
    style: 'sheridan',
    description: 'Sheridan - Short Raised Panel'
  },
  // Bronte Creek XL - Long carriage panel (1 row, columns based on width)
  BCXL: {
    type: 'carriage',
    rows: 1,
    cols: 'dynamic',
    style: 'bronte',
    description: 'Bronte Creek XL - Long Carriage Panel'
  },
  // Bronte Creek - Short carriage panel (2 rows, columns based on width)
  BC: {
    type: 'carriage',
    rows: 2,
    cols: 'dynamic',
    style: 'bronte',
    description: 'Bronte Creek - Short Carriage Panel'
  },
  // Trafalgar - Vertical ribbed
  TRAFALGAR: {
    type: 'ribbed',
    ribs: 8,
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
  // Muskoka - Carriage house design
  MUSKOKA: {
    type: 'carriage',
    rows: 2,
    cols: 2,
    style: 'muskoka',
    description: 'Muskoka - Carriage House'
  },
  // Denison - Carriage house design
  DENISON: {
    type: 'carriage',
    rows: 2,
    cols: 3,
    style: 'denison',
    description: 'Denison - Carriage House'
  },
  // Granville - Carriage house design
  GRANVILLE: {
    type: 'carriage',
    rows: 1,
    cols: 4,
    style: 'granville',
    description: 'Granville - Carriage House'
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
  FRENCH_OAK: '#C4A35A',
  // Aluminum
  CLEAR_ANODIZED: '#C0C0C0',
}

// Woodgrain patterns - colors for grain effect
const WOODGRAIN_COLORS = {
  WALNUT: { base: '#4A3728', light: '#5D432C', dark: '#3D2B1F' },
  ENGLISH_CHESTNUT: { base: '#6B4423', light: '#8B5A2B', dark: '#5C3317' },
  FRENCH_OAK: { base: '#C4A35A', light: '#D4B56A', dark: '#B49A4A' },
}

// Check if a color is a woodgrain finish
const isWoodgrain = (colorId) => {
  return ['WALNUT', 'ENGLISH_CHESTNUT', 'FRENCH_OAK'].includes(colorId)
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
}

function DoorPreview({
  width = 96, // inches
  height = 84, // inches
  color = 'WHITE',
  panelDesign = 'SHXL',
  windowInsert = null,
  windowPositions = [],  // Array of {section, col} for multi-stamp windows
  windowSection = 1,  // Legacy: single section (used if windowPositions empty)
  hasInserts = false,  // Whether decorative inserts are added
  glassColor = 'CLEAR',  // Glass color: CLEAR, ETCHED, SUPER_GREY
  windowQty = 0,  // For commercial doors
  windowFrameColor = 'WHITE',  // For commercial doors (WHITE or BLACK)
  doorType = 'residential',
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

  // Calculate stamp columns for current door width
  const stampColumns = getStampColumns(width)

  // Calculate section heights
  const sectionConfig = useMemo(() => {
    // Determine number of sections based on height
    let sections = []
    const remainingHeight = height

    if (height <= 84) {
      sections = [21, 21, 21, 21]
    } else if (height <= 96) {
      sections = [24, 24, 24, 24]
    } else if (height <= 120) {
      sections = [24, 24, 24, 24, 24]
    } else if (height <= 144) {
      sections = [24, 24, 24, 24, 24, 24]
    } else if (height <= 168) {
      sections = [24, 24, 24, 24, 24, 24, 24]
    } else {
      sections = [24, 24, 24, 24, 24, 24, 24, 24]
    }

    return sections
  }, [height])

  const totalSectionHeight = sectionConfig.reduce((a, b) => a + b, 0)
  const sectionHeightScale = height / totalSectionHeight

  // Get colors
  const doorColor = COLOR_MAP[color] || COLOR_MAP.WHITE
  const isDark = ['BLACK', 'WALNUT', 'IRON_ORE', 'NEW_BROWN', 'ENGLISH_CHESTNUT'].includes(color)
  const lineColor = isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.2)'
  const shadowColor = isDark ? 'rgba(0,0,0,0.5)' : 'rgba(0,0,0,0.15)'

  // Render panel design
  // Render window overlays for panel types that don't natively handle stamps (flush, ribbed, UDC)
  const renderWindowOverlays = (y, w, h, padding, sectionIndex) => {
    const absoluteSection = sectionIndex + 1
    const cols = getStampColumns(width)
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

  const renderPanelDesign = (sectionIndex, sectionY, sectionHeight) => {
    const pattern = PANEL_PATTERNS[panelDesign] || PANEL_PATTERNS.FLUSH
    const padding = displayWidth * 0.02
    const panelWidth = displayWidth - padding * 2
    const panelHeight = sectionHeight - padding * 2

    // For commercial doors, still use section-level window rendering
    if (isCommercial && windowInsert && windowInsert !== 'NONE' &&
        sectionIndex === (windowSection - 1) && windowQty > 0) {
      return renderCommercialWindows(sectionY + padding, panelWidth, panelHeight, padding)
    }

    // Raised and carriage panels handle window rendering inline per-stamp
    switch (pattern.type) {
      case 'raised':
        return renderRaisedPanels(sectionY + padding, panelWidth, panelHeight, padding, pattern, sectionIndex)
      case 'carriage':
        return renderCarriagePanels(sectionY + padding, panelWidth, panelHeight, padding, pattern, sectionIndex)
      case 'ribbed':
      case 'horizontal_ribbed':
      case 'flush':
      default: {
        // Render base panel pattern, then overlay windows on top
        let baseElements
        if (pattern.type === 'ribbed') {
          baseElements = renderRibbedPanels(sectionY + padding, panelWidth, panelHeight, padding, pattern)
        } else if (pattern.type === 'horizontal_ribbed') {
          baseElements = renderHorizontalRibbedPanels(sectionY + padding, panelWidth, panelHeight, padding, pattern)
        } else {
          baseElements = renderFlushPanel(sectionY + padding, panelWidth, panelHeight, padding)
        }
        const windowOverlays = renderWindowOverlays(sectionY + padding, panelWidth, panelHeight, padding, sectionIndex)
        if (windowOverlays.length > 0) {
          return <>{baseElements}{windowOverlays}</>
        }
        return baseElements
      }
    }
  }

  // Render commercial windows (multiple windows across top section)
  const renderCommercialWindows = (y, w, h, padding) => {
    const elements = []
    const frameColor = windowFrameColor === 'BLACK' ? '#1a1a1a' : '#FFFFFF'
    const frameStroke = windowFrameColor === 'BLACK' ? '#000' : '#888'

    // Get window dimensions based on type
    const windowSizes = {
      '24X12_THERMOPANE': { width: 24, height: 12 },
      '34X16_THERMOPANE': { width: 34, height: 16 },
      '18X8_THERMOPANE': { width: 18, height: 8 },
    }
    const windowSize = windowSizes[windowInsert] || { width: 24, height: 12 }

    // Calculate scaled window dimensions
    const scaleRatio = displayWidth / width
    const scaledWindowWidth = windowSize.width * scaleRatio * 0.9
    const scaledWindowHeight = Math.min(h * 0.7, windowSize.height * scaleRatio * 1.5)

    // Calculate spacing
    const totalWindowWidth = scaledWindowWidth * windowQty
    const spaces = windowQty + 1
    const spacing = (w - totalWindowWidth) / spaces

    // Render each window
    for (let i = 0; i < windowQty; i++) {
      const windowX = padding + spacing + i * (scaledWindowWidth + spacing)
      const windowY = y + (h - scaledWindowHeight) / 2

      elements.push(
        <g key={`commercial-window-${i}`}>
          {/* Window frame (outside color) */}
          <rect
            x={windowX - 3}
            y={windowY - 3}
            width={scaledWindowWidth + 6}
            height={scaledWindowHeight + 6}
            fill={frameColor}
            stroke={frameStroke}
            strokeWidth="2"
            rx="1"
          />
          {/* Glass */}
          <rect
            x={windowX}
            y={windowY}
            width={scaledWindowWidth}
            height={scaledWindowHeight}
            fill="#87CEEB"
            stroke="#666"
            strokeWidth="1"
          />
          {/* Glass reflection */}
          <rect
            x={windowX + 2}
            y={windowY + 2}
            width={scaledWindowWidth * 0.3}
            height={scaledWindowHeight * 0.4}
            fill="url(#glassReflection)"
            opacity="0.4"
          />
        </g>
      )
    }

    return elements
  }

  // Render a window within a single stamp area
  const renderStampWindow = (x, y, stampW, stampH, colIndex) => {
    const windowShape = WINDOW_SHAPES[windowInsert] || WINDOW_SHAPES.STOCKTON_STANDARD
    const frameColor = isDark ? '#888' : '#444'

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
    // Calculate columns dynamically based on door width
    const cols = pattern.cols === 'dynamic' ? getStampColumns(width) : pattern.cols
    // Gap between stamps
    const gapX = w * 0.02
    const gapY = h * 0.05
    // Calculate cell dimensions accounting for gaps
    const cellW = (w - gapX * (cols + 1)) / cols
    const cellH = (h - gapY * (rows + 1)) / rows

    const panels = []
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const x = padding + gapX + col * (cellW + gapX)
        const cellY = y + gapY + row * (cellH + gapY)
        const stampKey = `stamp-${sectionIndex}-${row}-${col}`

        // Check if this stamp has a window
        // Map stamp row within section to absolute section number
        const absoluteSection = sectionIndex + 1  // 1-based section
        if (hasWindowAtPosition(absoluteSection, col)) {
          // Render window instead of panel
          panels.push(
            <g key={stampKey}>
              {renderStampWindow(x, cellY, cellW, cellH, col)}
            </g>
          )
          continue
        }

        // Outer border inset from cell edge
        const outerInset = Math.min(cellW, cellH) * 0.05
        // Inner raised panel inset from outer border
        const innerInset = Math.min(cellW, cellH) * 0.12

        // Check if this stamp is being hovered (for interactive mode)
        const isHovered = interactive && highlightStamp &&
          highlightStamp.section === absoluteSection && highlightStamp.col === col

        panels.push(
          <g
            key={stampKey}
            style={interactive ? { cursor: 'pointer' } : {}}
            onClick={interactive && onStampClick ? () => onStampClick(absoluteSection, col) : undefined}
            onMouseEnter={interactive && onStampHover ? () => onStampHover(absoluteSection, col) : undefined}
            onMouseLeave={interactive && onStampHover ? () => onStampHover(null) : undefined}
          >
            {/* Highlight overlay for interactive mode */}
            {isHovered && (
              <rect
                x={x}
                y={cellY}
                width={cellW}
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
    // Calculate columns dynamically based on door width for Bronte Creek styles
    const cols = pattern.cols === 'dynamic' ? getStampColumns(width) : pattern.cols
    // Gap between stamps
    const gapX = w * 0.02
    const gapY = h * 0.05
    const cellW = (w - gapX * (cols + 1)) / cols
    const cellH = (h - gapY * (rows + 1)) / rows

    const panels = []
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const x = padding + gapX + col * (cellW + gapX)
        const cellY = y + gapY + row * (cellH + gapY)
        const stampKey = `carriage-${sectionIndex}-${row}-${col}`

        // Check if this stamp has a window
        const absoluteSection = sectionIndex + 1  // 1-based section
        if (hasWindowAtPosition(absoluteSection, col)) {
          // Render window instead of panel
          panels.push(
            <g key={stampKey}>
              {renderStampWindow(x, cellY, cellW, cellH, col)}
            </g>
          )
          continue
        }

        // Outer border inset
        const outerInset = Math.min(cellW, cellH) * 0.05
        // Inner frame inset
        const innerInset = Math.min(cellW, cellH) * 0.12
        const cornerRadius = Math.min(cellW, cellH) * 0.03

        // Check if this stamp is being hovered (for interactive mode)
        const isHovered = interactive && highlightStamp &&
          highlightStamp.section === absoluteSection && highlightStamp.col === col

        panels.push(
          <g
            key={stampKey}
            style={interactive ? { cursor: 'pointer' } : {}}
            onClick={interactive && onStampClick ? () => onStampClick(absoluteSection, col) : undefined}
            onMouseEnter={interactive && onStampHover ? () => onStampHover(absoluteSection, col) : undefined}
            onMouseLeave={interactive && onStampHover ? () => onStampHover(null) : undefined}
          >
            {/* Highlight overlay for interactive mode */}
            {isHovered && (
              <rect
                x={x}
                y={cellY}
                width={cellW}
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
            {/* Vertical divider line for Bronte Creek carriage style */}
            {(pattern.style === 'bronte' || pattern.style === 'carriage') && (
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

  // Render horizontal ribbed panels (for UDC commercial)
  const renderHorizontalRibbedPanels = (y, w, h, padding, pattern) => {
    const { ribs } = pattern
    const ribSpacing = h / (ribs + 1)
    const lines = []

    for (let i = 1; i <= ribs; i++) {
      const lineY = y + ribSpacing * i
      lines.push(
        <g key={`h-rib-${i}`}>
          <line
            x1={padding}
            y1={lineY - 1}
            x2={padding + w}
            y2={lineY - 1}
            stroke={shadowColor}
            strokeWidth="2"
          />
          <line
            x1={padding}
            y1={lineY}
            x2={padding + w}
            y2={lineY}
            stroke={isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.6)'}
            strokeWidth="1"
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

  const renderWindowSection = (y, w, h, padding) => {
    const windowShape = WINDOW_SHAPES[windowInsert] || WINDOW_SHAPES.STOCKTON_STANDARD
    const pattern = PANEL_PATTERNS[panelDesign] || PANEL_PATTERNS.SHXL
    const frameColor = isDark ? '#888' : '#444'

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
    const cols = pattern.cols === 'dynamic' ? getStampColumns(width) : pattern.cols
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
