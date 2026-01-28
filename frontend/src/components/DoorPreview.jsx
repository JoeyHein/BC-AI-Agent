/**
 * DoorPreview Component
 * Renders a visual preview of the door configuration in real-time
 * Shows panel layout, colors, window placement, and design patterns
 */

import { useMemo } from 'react'

// Panel design patterns as SVG patterns
const PANEL_PATTERNS = {
  SHXL: { // Sheridan - raised panel short
    type: 'raised',
    rows: 2,
    cols: 2,
    style: 'traditional'
  },
  LNXL: { // Sheridan XL - raised panel long
    type: 'raised',
    rows: 1,
    cols: 3,
    style: 'traditional'
  },
  SHCH: { // Bronte Creek - carriage house short
    type: 'carriage',
    rows: 2,
    cols: 2,
    style: 'carriage'
  },
  LNCH: { // Bronte Creek XL - carriage house long
    type: 'carriage',
    rows: 1,
    cols: 3,
    style: 'carriage'
  },
  RIB: { // Trafalgar - ribbed
    type: 'ribbed',
    ribs: 8,
    style: 'modern'
  },
  FLUSH: { // Flush - flat
    type: 'flush',
    style: 'minimal'
  },
  UDC: { // Commercial UDC (Undercoated) - 5 horizontal lines per panel
    type: 'ribbed',
    ribs: 5,
    style: 'commercial'
  },
  MUSKOKA: {
    type: 'carriage',
    rows: 2,
    cols: 2,
    style: 'rustic'
  },
  DENISON: {
    type: 'carriage',
    rows: 2,
    cols: 3,
    style: 'classic'
  },
  GRANVILLE: {
    type: 'carriage',
    rows: 1,
    cols: 4,
    style: 'farmhouse'
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
    // For commercial doors: windows in top section (section 0) based on windowQty
    // For residential doors: single window in specified section
    const hasWindow = windowInsert && windowInsert !== 'NONE' && (
      isCommercial
        ? (sectionIndex === 0 && windowQty > 0)  // Commercial: top section with quantity
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
    const { rows, cols } = pattern
    const cellW = (w - padding * (cols - 1)) / cols
    const cellH = (h - padding * (rows - 1)) / rows

    const panels = []
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const x = padding + col * (cellW + padding)
        const cellY = y + row * (cellH + padding)
        const inset = Math.min(cellW, cellH) * 0.1

        panels.push(
          <g key={`panel-${row}-${col}`}>
            {/* Outer raised panel border */}
            <rect
              x={x}
              y={cellY}
              width={cellW}
              height={cellH}
              fill={doorColor}
              stroke={lineColor}
              strokeWidth="1"
            />
            {/* Inner recessed area */}
            <rect
              x={x + inset}
              y={cellY + inset}
              width={cellW - inset * 2}
              height={cellH - inset * 2}
              fill={doorColor}
              stroke={lineColor}
              strokeWidth="0.5"
              style={{ filter: `drop-shadow(inset 2px 2px 4px ${shadowColor})` }}
            />
            {/* Highlight on top/left */}
            <line
              x1={x + inset}
              y1={cellY + inset}
              x2={x + cellW - inset}
              y2={cellY + inset}
              stroke={isDark ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.5)'}
              strokeWidth="1"
            />
            <line
              x1={x + inset}
              y1={cellY + inset}
              x2={x + inset}
              y2={cellY + cellH - inset}
              stroke={isDark ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.5)'}
              strokeWidth="1"
            />
          </g>
        )
      }
    }
    return panels
  }

  const renderCarriagePanels = (y, w, h, padding, pattern) => {
    const { rows, cols } = pattern
    const cellW = (w - padding * (cols - 1)) / cols
    const cellH = (h - padding * (rows - 1)) / rows

    const panels = []
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const x = padding + col * (cellW + padding)
        const cellY = y + row * (cellH + padding)
        const inset = Math.min(cellW, cellH) * 0.08
        const cornerRadius = Math.min(cellW, cellH) * 0.05

        panels.push(
          <g key={`carriage-${row}-${col}`}>
            {/* Outer border with rounded corners */}
            <rect
              x={x}
              y={cellY}
              width={cellW}
              height={cellH}
              rx={cornerRadius}
              ry={cornerRadius}
              fill={doorColor}
              stroke={lineColor}
              strokeWidth="1.5"
            />
            {/* Inner decorative frame */}
            <rect
              x={x + inset}
              y={cellY + inset}
              width={cellW - inset * 2}
              height={cellH - inset * 2}
              rx={cornerRadius * 0.5}
              ry={cornerRadius * 0.5}
              fill="none"
              stroke={lineColor}
              strokeWidth="1"
            />
            {/* Cross beam for carriage style */}
            {pattern.style === 'carriage' && (
              <>
                <line
                  x1={x + cellW * 0.5}
                  y1={cellY + inset}
                  x2={x + cellW * 0.5}
                  y2={cellY + cellH - inset}
                  stroke={lineColor}
                  strokeWidth="1"
                />
              </>
            )}
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
          <g key={`section-${section.index}`}>
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
