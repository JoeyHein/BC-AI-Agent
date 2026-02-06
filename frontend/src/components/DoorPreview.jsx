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

// Color hex values
const COLOR_MAP = {
  WHITE: '#FFFFFF',
  BRIGHT_WHITE: '#FFFFFF',
  NEW_ALMOND: '#EFDECD',
  BLACK: '#1a1a1a',
  WALNUT: '#5D432C',
  IRON_ORE: '#48464A',
  SANDTONE: '#D4C4A8',
  NEW_BROWN: '#6B4423',
  BRONZE: '#CD7F32',
  STEEL_GREY: '#71797E',
  HAZELWOOD: '#8E7618',
  ENGLISH_CHESTNUT: '#954535',
  CLEAR_ANODIZED: '#C0C0C0',
}

// Window insert shapes
const WINDOW_SHAPES = {
  STOCKTON_STANDARD: { type: 'grid', rows: 2, cols: 4, arched: false },
  STOCKTON_TEN_SQUARE_XL: { type: 'grid', rows: 2, cols: 5, arched: false },
  STOCKTON_ARCHED_XL: { type: 'grid', rows: 2, cols: 5, arched: true },
  STOCKTON_EIGHT_SQUARE: { type: 'grid', rows: 2, cols: 4, arched: false },
  STOCKTON_ARCHED: { type: 'grid', rows: 2, cols: 4, arched: true },
  STOCKBRIDGE_STRAIGHT: { type: 'prairie', arched: false },
  STOCKBRIDGE_STRAIGHT_XL: { type: 'prairie', arched: false, xl: true },
  STOCKBRIDGE_ARCHED_XL: { type: 'prairie', arched: true, xl: true },
  STOCKBRIDGE_ARCHED: { type: 'prairie', arched: true },
}

function DoorPreview({
  width = 96, // inches
  height = 84, // inches
  color = 'WHITE',
  panelDesign = 'SHXL',
  windowInsert = null,
  windowSection = 1,
  windowQty = 0,  // For commercial doors
  windowFrameColor = 'WHITE',  // For commercial doors (WHITE or BLACK)
  doorType = 'residential',
  showDimensions = true,
  scale = 1,
  interactive = false,  // Enable click-to-place window mode
  onSectionClick = null,  // Callback when section is clicked (section index)
  highlightSection = null,  // Section to highlight (for hover effect)
  onSectionHover = null,  // Callback when hovering over a section
}) {
  const isCommercial = doorType === 'commercial'
  // Calculate display dimensions (max 400px width for preview)
  const maxDisplayWidth = 400 * scale
  const aspectRatio = height / width
  const displayWidth = Math.min(maxDisplayWidth, 400)
  const displayHeight = displayWidth * aspectRatio

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
  const renderPanelDesign = (sectionIndex, sectionY, sectionHeight) => {
    const pattern = PANEL_PATTERNS[panelDesign] || PANEL_PATTERNS.FLUSH
    const padding = displayWidth * 0.02
    const panelWidth = displayWidth - padding * 2
    const panelHeight = sectionHeight - padding * 2

    // Check if this section has windows
    // For commercial doors: windows in selected section based on windowQty
    // For residential doors: single window in specified section
    const hasWindow = windowInsert && windowInsert !== 'NONE' && (
      isCommercial
        ? (sectionIndex === (windowSection - 1) && windowQty > 0)  // Commercial: selected section with quantity
        : (sectionIndex === windowSection - 1)   // Residential: specified section
    )

    if (hasWindow) {
      if (isCommercial) {
        return renderCommercialWindows(sectionY + padding, panelWidth, panelHeight, padding)
      }
      return renderWindowSection(sectionY + padding, panelWidth, panelHeight, padding)
    }

    switch (pattern.type) {
      case 'raised':
        return renderRaisedPanels(sectionY + padding, panelWidth, panelHeight, padding, pattern)
      case 'carriage':
        return renderCarriagePanels(sectionY + padding, panelWidth, panelHeight, padding, pattern)
      case 'ribbed':
        return renderRibbedPanels(sectionY + padding, panelWidth, panelHeight, padding, pattern)
      case 'horizontal_ribbed':
        return renderHorizontalRibbedPanels(sectionY + padding, panelWidth, panelHeight, padding, pattern)
      case 'flush':
      default:
        return renderFlushPanel(sectionY + padding, panelWidth, panelHeight, padding)
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

  const renderRaisedPanels = (y, w, h, padding, pattern) => {
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

        // Outer border inset from cell edge
        const outerInset = Math.min(cellW, cellH) * 0.05
        // Inner raised panel inset from outer border
        const innerInset = Math.min(cellW, cellH) * 0.12

        panels.push(
          <g key={`panel-${row}-${col}`}>
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

  const renderCarriagePanels = (y, w, h, padding, pattern) => {
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

        // Outer border inset
        const outerInset = Math.min(cellW, cellH) * 0.05
        // Inner frame inset
        const innerInset = Math.min(cellW, cellH) * 0.12
        const cornerRadius = Math.min(cellW, cellH) * 0.03

        panels.push(
          <g key={`carriage-${row}-${col}`}>
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
    const windowPadding = w * 0.1
    const windowWidth = w - windowPadding * 2
    const windowHeight = h * 0.7
    const windowY = y + (h - windowHeight) / 2
    const frameColor = isDark ? '#888' : '#444'

    const elements = []

    // Window frame
    elements.push(
      <rect
        key="window-frame"
        x={padding + windowPadding}
        y={windowY}
        width={windowWidth}
        height={windowHeight}
        fill="#87CEEB"
        stroke={frameColor}
        strokeWidth="3"
        rx="2"
        ry="2"
      />
    )

    // Window grid
    if (windowShape.type === 'grid') {
      const { rows, cols } = windowShape
      const cellW = windowWidth / cols
      const cellH = windowHeight / rows

      // Vertical lines
      for (let i = 1; i < cols; i++) {
        elements.push(
          <line
            key={`wv-${i}`}
            x1={padding + windowPadding + cellW * i}
            y1={windowY}
            x2={padding + windowPadding + cellW * i}
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
            x1={padding + windowPadding}
            y1={windowY + cellH * i}
            x2={padding + windowPadding + windowWidth}
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
            d={`M ${padding + windowPadding} ${windowY + 10}
                Q ${padding + windowPadding + windowWidth / 2} ${windowY - 15}
                  ${padding + windowPadding + windowWidth} ${windowY + 10}`}
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
          x={padding + windowPadding + borderSize}
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
        [padding + windowPadding, windowY],
        [padding + windowPadding + windowWidth - borderSize, windowY],
        [padding + windowPadding, windowY + windowHeight - borderSize],
        [padding + windowPadding + windowWidth - borderSize, windowY + windowHeight - borderSize],
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
        x={padding + windowPadding + 5}
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
        </defs>

        {/* Door background with shadow */}
        <rect
          x="0"
          y="0"
          width={displayWidth}
          height={displayHeight}
          fill={doorColor}
          stroke="#333"
          strokeWidth="2"
          filter="url(#doorShadow)"
        />

        {/* Render each section */}
        {sections.map((section) => (
          <g
            key={`section-${section.index}`}
            style={interactive ? { cursor: 'pointer' } : {}}
            onClick={interactive && onSectionClick ? () => onSectionClick(section.index + 1) : undefined}
            onMouseEnter={interactive && onSectionHover ? () => onSectionHover(section.index + 1) : undefined}
            onMouseLeave={interactive && onSectionHover ? () => onSectionHover(null) : undefined}
          >
            {/* Interactive highlight overlay */}
            {interactive && highlightSection === section.index + 1 && (
              <rect
                x="2"
                y={section.y + 2}
                width={displayWidth - 4}
                height={section.height - 4}
                fill="rgba(59, 130, 246, 0.2)"
                stroke="rgba(59, 130, 246, 0.8)"
                strokeWidth="2"
                strokeDasharray="5,3"
                rx="3"
              />
            )}
            {/* Section number label for interactive mode */}
            {interactive && (
              <text
                x={displayWidth - 15}
                y={section.y + 18}
                fontSize="12"
                fill={highlightSection === section.index + 1 ? '#2563eb' : '#666'}
                fontWeight={highlightSection === section.index + 1 ? 'bold' : 'normal'}
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
            {/* Panel design */}
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
