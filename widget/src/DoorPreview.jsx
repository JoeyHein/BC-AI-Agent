/**
 * DoorPreview Component — Extracted from OPENDC Dealer Portal
 * Pure presentational SVG door renderer. No API calls, no external dependencies.
 * Renders doors as pure SVG with panel designs, window inserts, colors, and woodgrain patterns.
 */

import { useMemo } from 'react'

// Stamp dimensions (inches)
const STAMP_WIDTH = 42
const STAMP_HEIGHT = 14

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
  // BC (Bronte Creek): ~24" stamps
  const isBronte = panelDesign === 'BC'
  if (isBronte) {
    // BC: 8'=3, 9'=3, 10'=4, 12'=5, 14'=6, 16'=7, 18'=8
    if (widthFeet <= 9) return 3
    if (widthFeet <= 10) return 4
    if (widthFeet <= 12) return 5
    if (widthFeet <= 14) return 6
    if (widthFeet <= 16) return 7
    if (widthFeet <= 18) return 8
    return 9
  } else {
    // SH: 8'=4, 9'=4, 10'=5, 12'=6, 14'=7, 16'=8, 18'=9
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
  SHXL: { type: 'raised', rows: 1, cols: 'dynamic', stampType: 'long', style: 'sheridan', description: 'Sheridan XL - Long Raised Panel' },
  SH: { type: 'raised', rows: 1, cols: 'dynamic', stampType: 'standard', style: 'sheridan', description: 'Sheridan - Short Raised Panel' },
  BCXL: { type: 'carriage', rows: 1, cols: 'dynamic', stampType: 'long', style: 'bronte', description: 'Bronte Creek XL - Long Carriage Panel' },
  BC: { type: 'carriage', rows: 1, cols: 'dynamic', stampType: 'standard', style: 'bronte', description: 'Bronte Creek - Short Carriage Panel' },
  TRAFALGAR: { type: 'horizontal_ribbed', ribs: 5, style: 'modern', description: 'Trafalgar - Ribbed' },
  FLUSH: { type: 'flush', style: 'minimal', description: 'Flush - Flat Panel' },
  UDC: { type: 'horizontal_ribbed', ribs: 5, style: 'commercial', description: 'UDC - Commercial Standard' },
  MUSKOKA: { type: 'xbrace', style: 'muskoka', description: 'Muskoka - X-Brace Barn Door' },
  DENISON: { type: 'raised_grid', style: 'denison', description: 'Denison - Raised Panel Grid' },
  GRANVILLE: { type: 'raised_grid', style: 'granville', description: 'Granville - Raised Panels (Wide)' },
}

const COLOR_MAP = {
  WHITE: '#F4F4F4',
  BRIGHT_WHITE: '#F4F4F4',
  BLACK: '#282828',
  NEW_BROWN: '#4C4842',
  HAZELWOOD: '#756F61',
  BRONZE: '#6C6961',
  STEEL_GREY: '#7D7F7D',
  SANDTONE: '#A4957D',
  IRON_ORE: '#2F3234',
  WALNUT: '#4A3728',
  ENGLISH_CHESTNUT: '#6B4423',
  FRENCH_OAK: '#C2B078',
  CLEAR_ANODIZED: '#C0C0C0',
  BLACK_ANODIZED: '#1a1a1a',
  MILL: '#D3D3D3',
}

const WOODGRAIN_COLORS = {
  WALNUT: { base: '#4A3728', light: '#5D432C', dark: '#3D2B1F' },
  ENGLISH_CHESTNUT: { base: '#6B4423', light: '#8B5A2B', dark: '#5C3317' },
  FRENCH_OAK: { base: '#C2B078', light: '#C2B078', dark: '#8A6642' },
}

const isWoodgrain = (colorId) => ['WALNUT', 'ENGLISH_CHESTNUT', 'FRENCH_OAK'].includes(colorId)

const darkenHex = (hex, factor = 0.75) => {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  const dr = Math.round(r * factor)
  const dg = Math.round(g * factor)
  const db = Math.round(b * factor)
  return `#${dr.toString(16).padStart(2, '0')}${dg.toString(16).padStart(2, '0')}${db.toString(16).padStart(2, '0')}`
}

const resolveFrameColor = (frameColorId, doorColorHex, doorColorId) => {
  if (frameColorId === 'MATCH' || !frameColorId) {
    if (isWoodgrain(doorColorId) && WOODGRAIN_COLORS[doorColorId]) {
      return { fill: WOODGRAIN_COLORS[doorColorId].dark, stroke: darkenHex(WOODGRAIN_COLORS[doorColorId].dark, 0.7) }
    }
    return { fill: darkenHex(doorColorHex, 0.75), stroke: darkenHex(doorColorHex, 0.55) }
  }
  const hex = COLOR_MAP[frameColorId] || doorColorHex
  return { fill: hex, stroke: darkenHex(hex, 0.7) }
}

const WINDOW_SIZES = {
  LONG: { width: 40, height: 14 },
  SHORT: { width: 20, height: 14 },
}

const WINDOW_SHAPES = {
  STOCKTON_STANDARD: { type: 'grid', rows: 2, cols: 4, arched: false, size: 'LONG' },
  STOCKTON_TEN_SQUARE_XL: { type: 'grid', rows: 2, cols: 5, arched: false, size: 'LONG' },
  STOCKTON_ARCHED_XL: { type: 'grid', rows: 2, cols: 5, arched: true, size: 'LONG' },
  STOCKTON_EIGHT_SQUARE: { type: 'grid', rows: 2, cols: 4, arched: false, size: 'LONG' },
  STOCKTON_ARCHED: { type: 'grid', rows: 2, cols: 4, arched: true, size: 'LONG' },
  STOCKBRIDGE_STRAIGHT: { type: 'prairie', arched: false, size: 'LONG' },
  STOCKBRIDGE_STRAIGHT_XL: { type: 'prairie', arched: false, xl: true, size: 'LONG' },
  STOCKBRIDGE_ARCHED_XL: { type: 'prairie', arched: true, xl: true, size: 'LONG' },
  STOCKBRIDGE_ARCHED: { type: 'prairie', arched: true, size: 'LONG' },
  STOCKTON_SHORT: { type: 'grid', rows: 2, cols: 2, arched: false, size: 'SHORT' },
  STOCKTON_SHORT_ARCHED: { type: 'grid', rows: 2, cols: 2, arched: true, size: 'SHORT' },
  PLAIN_LONG: { type: 'plain', rows: 0, cols: 0, arched: false, size: 'LONG' },
  PLAIN_SHORT: { type: 'plain', rows: 0, cols: 0, arched: false, size: 'SHORT' },
}

function DoorPreview({
  width = 192,
  height = 96,
  color = 'WHITE',
  panelDesign = 'SHXL',
  windowInsert = null,
  windowPositions = [],
  windowSection = 1,
  windowSize = 'long',
  hasInserts = true,
  glassColor = 'CLEAR',
  windowQty = 0,
  windowPanels = null,
  windowFrameColor = 'MATCH',
  doorType = 'residential',
  doorSeries = '',
  showDimensions = false,
  scale = 1,
  maxWidth = 400,
  interactive = false,
  onStampClick = null,
  onStampHover = null,
  highlightStamp = null,
}) {
  const isCommercial = doorType === 'commercial'
  const maxDisplayWidth = maxWidth * scale
  const aspectRatio = height / width
  const displayWidth = Math.min(maxDisplayWidth, maxWidth)
  const displayHeight = displayWidth * aspectRatio

  const hasWindowAtPosition = (section, col) => {
    if (windowPositions && windowPositions.length > 0) {
      return windowPositions.some(pos => pos.section === section && pos.col === col)
    }
    return false
  }

  const hasAnyWindows = windowInsert && windowInsert !== 'NONE' && (
    windowPositions && windowPositions.length > 0
  )

  const isCraft = doorSeries === 'CRAFT'
  const currentPattern = PANEL_PATTERNS[panelDesign] || PANEL_PATTERNS.SHXL
  const stampColumns = getStampColumns(width, currentPattern.stampType, isCraft, panelDesign)

  const sectionConfig = useMemo(() => {
    if (isCraft) {
      const sectionH = height <= 84 ? 28 : 32
      return [sectionH, sectionH, sectionH]
    }
    if (height <= 84) return [21, 21, 21, 21]
    else if (height <= 96) return [24, 24, 24, 24]
    else if (height <= 120) return [24, 24, 24, 24, 24]
    else if (height <= 144) return [24, 24, 24, 24, 24, 24]
    else if (height <= 168) return [24, 24, 24, 24, 24, 24, 24]
    else return [24, 24, 24, 24, 24, 24, 24, 24]
  }, [height, isCraft])

  const totalSectionHeight = sectionConfig.reduce((a, b) => a + b, 0)
  const sectionHeightScale = height / totalSectionHeight

  const doorColor = COLOR_MAP[color] || COLOR_MAP.WHITE
  const isDark = ['BLACK', 'WALNUT', 'IRON_ORE', 'NEW_BROWN', 'ENGLISH_CHESTNUT'].includes(color)
  const lineColor = isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.2)'
  const shadowColor = isDark ? 'rgba(0,0,0,0.5)' : 'rgba(0,0,0,0.15)'
  const resolvedFrame = resolveFrameColor(windowFrameColor, doorColor, color)

  const isAluminium = doorType === 'aluminium'

  // Unique ID for this instance to avoid SVG id collisions when multiple previews on page
  const instanceId = useMemo(() => Math.random().toString(36).substr(2, 9), [])

  const renderWindowOverlays = (y, w, h, padding, sectionIndex) => {
    const absoluteSection = sectionIndex + 1
    const cols = getStampColumns(width, currentPattern.stampType, isCraft, panelDesign)
    const gapX = w * 0.02
    const cellW = (w - gapX * (cols + 1)) / cols
    const cellH = h

    const windows = []
    for (let col = 0; col < cols; col++) {
      const x = padding + gapX + col * (cellW + gapX)
      if (hasWindowAtPosition(absoluteSection, col)) {
        windows.push(
          <g key={`window-overlay-${sectionIndex}-${col}`}
            style={interactive ? { cursor: 'pointer' } : {}}
            onClick={interactive && onStampClick ? () => onStampClick(absoluteSection, col) : undefined}
            onMouseEnter={interactive && onStampHover ? () => onStampHover(absoluteSection, col) : undefined}
            onMouseLeave={interactive && onStampHover ? () => onStampHover(null) : undefined}
          >
            {renderStampWindow(x, y, cellW, cellH, col)}
          </g>
        )
      } else if (interactive) {
        const isHovered = highlightStamp &&
          highlightStamp.section === absoluteSection &&
          highlightStamp.col === col
        windows.push(
          <g key={`interactive-overlay-${sectionIndex}-${col}`}
            style={{ cursor: 'pointer' }}
            onClick={onStampClick ? () => onStampClick(absoluteSection, col) : undefined}
            onMouseEnter={onStampHover ? () => onStampHover(absoluteSection, col) : undefined}
            onMouseLeave={onStampHover ? () => onStampHover(null) : undefined}
          >
            <rect x={x} y={y} width={cellW} height={cellH}
              fill={isHovered ? 'rgba(201, 169, 110, 0.2)' : 'transparent'}
              stroke={isHovered ? 'rgba(201, 169, 110, 0.8)' : 'none'}
              strokeWidth="2" strokeDasharray="4,2" rx="2" />
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

    if (isAluminium) {
      return renderAluminumSection(sectionY, sectionHeight, padding, panelWidth, sectionIndex)
    }

    if (isCommercial && windowInsert === 'V130G' && windowQty > 0) {
      const hasV130G = windowPanels
        ? !!(windowPanels[sectionIndex + 1]?.qty)
        : (sectionIndex >= ((windowSection || 1) - 1) && sectionIndex < ((windowSection || 1) - 1) + windowQty)
      if (hasV130G) {
        return renderV130GSection(sectionY, sectionHeight, padding, panelWidth)
      }
    }

    const panelNum = sectionIndex + 1
    const panelWindowQty = windowPanels ? (windowPanels[panelNum]?.qty || 0) : (sectionIndex === (windowSection - 1) ? windowQty : 0)
    const hasCommercialWindows = isCommercial && windowInsert && windowInsert !== 'NONE' && windowInsert !== 'V130G' && panelWindowQty > 0

    if (pattern.type === 'xbrace' || pattern.type === 'raised_grid') {
      return renderCraftSection(sectionIndex, sectionY, sectionHeight, pattern)
    }

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

    if (hasCommercialWindows) {
      const windowOverlay = renderCommercialWindows(sectionY + padding, panelWidth, panelHeight, padding, sectionIndex, panelWindowQty)
      return <>{baseElements}{windowOverlay}</>
    }

    if (pattern.type !== 'raised' && pattern.type !== 'carriage') {
      const windowOverlays = renderWindowOverlays(sectionY + padding, panelWidth, panelHeight, padding, sectionIndex)
      if (windowOverlays.length > 0 || interactive) {
        return <>{baseElements}{windowOverlays}</>
      }
    }

    return baseElements
  }

  const renderV130GSection = (sectionY, sectionHeight, padding, panelWidth) => {
    const elements = []
    const v130gFrameColors = {
      WHITE: { fill: '#E8E8E8', stroke: '#B0B0B0' },
      BRIGHT_WHITE: { fill: '#E8E8E8', stroke: '#B0B0B0' },
      BLACK: { fill: '#1a1a1a', stroke: '#000000' },
      STEEL_GREY: { fill: '#A0A0A0', stroke: '#787878' },
    }
    const v130gFrame = v130gFrameColors[color] || v130gFrameColors.STEEL_GREY
    const frameColor = v130gFrame.fill
    const frameStroke = v130gFrame.stroke
    const glassColors = { 'CLEAR': '#87CEEB', 'ETCHED': '#D3D3D3', 'SUPER_GREY': '#3D3D3D' }
    const glassFill = glassColors[glassColor] || glassColors['CLEAR']

    const x = padding
    const y = sectionY
    const w = panelWidth
    const h = sectionHeight
    const framePad = 3
    const mullionW = 3

    const widthFeet = width / 12
    let paneCount
    if (widthFeet <= 10) paneCount = 3
    else if (widthFeet <= 14) paneCount = 4
    else if (widthFeet <= 18) paneCount = 5
    else if (widthFeet <= 22) paneCount = 6
    else paneCount = 7

    elements.push(
      <rect key="v130g-frame" x={x} y={y} width={w} height={h}
        fill={frameColor} stroke={frameStroke} strokeWidth="1.5" rx="1" />
    )

    const innerX = x + framePad
    const innerY = y + framePad
    const innerW = w - framePad * 2
    const innerH = h - framePad * 2
    const totalMullionW = mullionW * (paneCount - 1)
    const paneW = (innerW - totalMullionW) / paneCount

    for (let i = 0; i < paneCount; i++) {
      const paneX = innerX + i * (paneW + mullionW)
      elements.push(
        <rect key={`v130g-glass-${i}`} x={paneX} y={innerY}
          width={paneW} height={innerH}
          fill={glassFill} stroke={frameStroke} strokeWidth="0.5" />
      )
      elements.push(
        <rect key={`v130g-reflect-${i}`}
          x={paneX + paneW * 0.08} y={innerY + innerH * 0.08}
          width={paneW * 0.25} height={innerH * 0.4}
          fill="rgba(255,255,255,0.25)" rx="1" />
      )
    }
    return <g key="v130g-section">{elements}</g>
  }

  const renderAluminumSection = (sectionY, sectionHeight, padding, panelWidth, sectionIndex) => {
    const elements = []
    const aluminumFrames = {
      CLEAR_ANODIZED: { fill: '#B8B8B8', stroke: '#909090', highlight: '#D0D0D0' },
      BLACK_ANODIZED: { fill: '#2A2A2A', stroke: '#111111', highlight: '#444444' },
      WHITE: { fill: '#E8E8E8', stroke: '#C0C0C0', highlight: '#FFFFFF' },
      BRIGHT_WHITE: { fill: '#E8E8E8', stroke: '#C0C0C0', highlight: '#FFFFFF' },
      MILL: { fill: '#CCCCCC', stroke: '#A0A0A0', highlight: '#DDDDDD' },
    }
    const frame = aluminumFrames[color] || aluminumFrames.CLEAR_ANODIZED

    const glassLookup = {
      'CLEAR': { fill: '#A8D8EA', reflection: 'rgba(255,255,255,0.35)' },
      'ETCHED': { fill: '#D3D3D3', reflection: 'rgba(255,255,255,0.2)' },
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
    const frameW = 4
    const mullionW = 3
    const outerRailH = padding + frameW
    const innerRailH = 2

    const topInset = isFirst ? outerRailH : innerRailH
    const bottomInset = isLast ? outerRailH : innerRailH

    elements.push(
      <rect key={`al-frame-${sectionIndex}`}
        x={x} y={y} width={w} height={h}
        fill={frame.fill} stroke={frame.stroke} strokeWidth="1" rx="0.5" />
    )

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

    // AL976: glass panes with vertical stiles
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
      elements.push(
        <rect key={`al-glass-${sectionIndex}-${i}`}
          x={paneX} y={innerY} width={paneW} height={innerH}
          fill={glass.fill} stroke={frame.stroke} strokeWidth="0.3" />
      )
      elements.push(
        <rect key={`al-reflect-${sectionIndex}-${i}`}
          x={paneX + paneW * 0.06} y={innerY + innerH * 0.06}
          width={paneW * 0.2} height={innerH * 0.35}
          fill={glass.reflection} rx="0.5"
          transform={`skewX(-3)`} />
      )
    }

    if (paneCount % 2 === 0) {
      const centerIdx = paneCount / 2 - 1
      const centerX = innerX + centerIdx * (paneW + mullionW) + paneW
      elements.push(
        <rect key={`al-stile-${sectionIndex}`}
          x={centerX - 0.5} y={innerY} width={mullionW + 1} height={innerH}
          fill={frame.fill} stroke="none" />
      )
    }

    return <g key={`al-section-${sectionIndex}`}>{elements}</g>
  }

  const renderCommercialWindows = (y, w, h, padding, sectionIdx = 0, qty = windowQty) => {
    const elements = []
    const frameColor = windowFrameColor === 'BLACK' ? '#1a1a1a' : '#FFFFFF'
    const frameStroke = windowFrameColor === 'BLACK' ? '#000' : '#888'

    const windowSizesMap = {
      '24X12_THERMOPANE': { width: 24, height: 12 },
      '34X16_THERMOPANE': { width: 34, height: 16 },
      '18X8_THERMOPANE': { width: 18, height: 8 },
    }
    const winSize = windowSizesMap[windowInsert] || { width: 24, height: 12 }
    const sectionInches = sectionConfig[sectionIdx] || 24

    const hScale = w / width
    const vScale = h / sectionInches

    const scaledWindowWidth = winSize.width * hScale
    const scaledWindowHeight = winSize.height * vScale
    const frameThickness = Math.max(2, 2.5 * hScale)

    const totalWindowWidth = scaledWindowWidth * qty
    const spaces = qty + 1
    const spacing = (w - totalWindowWidth) / spaces

    for (let i = 0; i < qty; i++) {
      const windowX = padding + spacing + i * (scaledWindowWidth + spacing)
      const windowY = y + (h - scaledWindowHeight) / 2

      elements.push(
        <g key={`commercial-window-${sectionIdx}-${i}`}>
          <rect x={windowX - frameThickness - 1} y={windowY - frameThickness - 1}
            width={scaledWindowWidth + (frameThickness + 1) * 2} height={scaledWindowHeight + (frameThickness + 1) * 2}
            fill={doorColor} stroke="none" />
          <rect x={windowX - frameThickness} y={windowY - frameThickness}
            width={scaledWindowWidth + frameThickness * 2} height={scaledWindowHeight + frameThickness * 2}
            fill={frameColor} stroke={frameStroke} strokeWidth="1.5" rx="1" />
          <rect x={windowX} y={windowY} width={scaledWindowWidth} height={scaledWindowHeight}
            fill="#87CEEB" stroke="#5a8fa8" strokeWidth="0.5" />
          <rect x={windowX + 2} y={windowY + 2}
            width={scaledWindowWidth * 0.25} height={scaledWindowHeight * 0.35}
            fill="rgba(255,255,255,0.3)" rx="1" />
        </g>
      )
    }
    return elements
  }

  const renderStampWindow = (x, y, stampW, stampH, colIndex) => {
    const windowShape = WINDOW_SHAPES[windowInsert] || WINDOW_SHAPES.STOCKTON_STANDARD
    const frameColor = resolvedFrame.stroke

    const glassColorMap = { 'CLEAR': '#87CEEB', 'ETCHED': '#D3D3D3', 'SUPER_GREY': '#3D3D3D' }
    const glassFill = glassColorMap[glassColor] || glassColorMap.CLEAR

    const windowPadding = Math.min(stampW, stampH) * 0.08
    const windowWidth = stampW - windowPadding * 2
    const windowHeight = stampH - windowPadding * 2
    const windowX = x + windowPadding
    const windowY = y + windowPadding

    const elements = []

    elements.push(
      <rect key={`window-frame-${colIndex}`}
        x={windowX} y={windowY} width={windowWidth} height={windowHeight}
        fill={glassFill} stroke={frameColor} strokeWidth="2" rx="2" ry="2" />
    )

    if (!hasInserts || windowShape.type === 'plain') {
      elements.push(
        <rect key={`reflection-${colIndex}`}
          x={windowX + 3} y={windowY + 3}
          width={windowWidth * 0.25} height={windowHeight * 0.35}
          fill={`url(#glassReflection-${instanceId})`} opacity="0.3" />
      )
      return elements
    }

    if (windowShape.type === 'grid') {
      const { rows, cols: gridCols } = windowShape
      const cellW = windowWidth / gridCols
      const cellH = windowHeight / rows

      for (let i = 1; i < gridCols; i++) {
        elements.push(
          <line key={`wv-${colIndex}-${i}`}
            x1={windowX + cellW * i} y1={windowY}
            x2={windowX + cellW * i} y2={windowY + windowHeight}
            stroke={frameColor} strokeWidth="1.5" />
        )
      }
      for (let i = 1; i < rows; i++) {
        elements.push(
          <line key={`wh-${colIndex}-${i}`}
            x1={windowX} y1={windowY + cellH * i}
            x2={windowX + windowWidth} y2={windowY + cellH * i}
            stroke={frameColor} strokeWidth="1.5" />
        )
      }

      if (windowShape.arched) {
        const archHeight = windowHeight * 0.15
        elements.push(
          <path key={`arch-${colIndex}`}
            d={`M ${windowX} ${windowY + archHeight} Q ${windowX + windowWidth / 2} ${windowY - archHeight * 0.5} ${windowX + windowWidth} ${windowY + archHeight}`}
            fill="none" stroke={frameColor} strokeWidth="2" />
        )
      }
    } else if (windowShape.type === 'prairie') {
      const borderSize = windowWidth * 0.12
      elements.push(
        <rect key={`prairie-inner-${colIndex}`}
          x={windowX + borderSize} y={windowY + borderSize}
          width={windowWidth - borderSize * 2} height={windowHeight - borderSize * 2}
          fill="none" stroke={frameColor} strokeWidth="1.5" />
      )
      const corners = [
        [windowX, windowY],
        [windowX + windowWidth - borderSize, windowY],
        [windowX, windowY + windowHeight - borderSize],
        [windowX + windowWidth - borderSize, windowY + windowHeight - borderSize],
      ]
      corners.forEach(([cx, cy], i) => {
        elements.push(
          <rect key={`corner-${colIndex}-${i}`}
            x={cx} y={cy} width={borderSize} height={borderSize}
            fill="none" stroke={frameColor} strokeWidth="1" />
        )
      })
    }

    elements.push(
      <rect key={`reflection-${colIndex}`}
        x={windowX + 3} y={windowY + 3}
        width={windowWidth * 0.25} height={windowHeight * 0.35}
        fill={`url(#glassReflection-${instanceId})`} opacity="0.3" />
    )

    return elements
  }

  const renderRaisedPanels = (y, w, h, padding, pattern, sectionIndex) => {
    const { rows } = pattern
    const cols = pattern.cols === 'dynamic' ? getStampColumns(width, pattern.stampType, isCraft, panelDesign) : pattern.cols
    const gapX = w * 0.012
    const gapY = h * 0.03
    const cellW = (w - gapX * (cols + 1)) / cols
    const cellH = (h - gapY * (rows + 1)) / rows

    const isLongOnStandard = windowSize === 'long' && pattern.stampType === 'standard'

    const panels = []
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const x = padding + gapX + col * (cellW + gapX)
        const cellY = y + gapY + row * (cellH + gapY)
        const stampKey = `stamp-${sectionIndex}-${row}-${col}`
        const absoluteSection = sectionIndex + 1

        if (isLongOnStandard && col % 2 === 1 && hasWindowAtPosition(absoluteSection, col - 1)) continue

        if (hasWindowAtPosition(absoluteSection, col)) {
          const windowW = isLongOnStandard ? cellW * 2 + gapX : cellW
          panels.push(
            <g key={stampKey}
              style={interactive ? { cursor: 'pointer' } : {}}
              onClick={interactive && onStampClick ? () => onStampClick(absoluteSection, isLongOnStandard ? Math.floor(col / 2) * 2 : col) : undefined}
              onMouseEnter={interactive && onStampHover ? () => onStampHover(absoluteSection, col) : undefined}
              onMouseLeave={interactive && onStampHover ? () => onStampHover(null) : undefined}
            >
              {renderStampWindow(x, cellY, windowW, cellH, col)}
            </g>
          )
          continue
        }

        const outerInset = Math.min(cellW, cellH) * 0.05
        const innerInset = Math.min(cellW, cellH) * 0.12

        const clickCol = isLongOnStandard ? Math.floor(col / 2) * 2 : col
        const pairStart = isLongOnStandard ? Math.floor(col / 2) * 2 : col
        const isHovered = interactive && highlightStamp &&
          highlightStamp.section === absoluteSection &&
          (isLongOnStandard
            ? Math.floor(highlightStamp.col / 2) * 2 === pairStart
            : highlightStamp.col === col)

        panels.push(
          <g key={stampKey}
            style={interactive ? { cursor: 'pointer' } : {}}
            onClick={interactive && onStampClick ? () => onStampClick(absoluteSection, clickCol) : undefined}
            onMouseEnter={interactive && onStampHover ? () => onStampHover(absoluteSection, col) : undefined}
            onMouseLeave={interactive && onStampHover ? () => onStampHover(null) : undefined}
          >
            {isHovered && (isLongOnStandard ? col % 2 === 0 : true) && (
              <rect x={x} y={cellY}
                width={isLongOnStandard ? cellW * 2 + gapX : cellW} height={cellH}
                fill="rgba(201, 169, 110, 0.2)" stroke="rgba(201, 169, 110, 0.8)"
                strokeWidth="2" strokeDasharray="4,2" rx="2" />
            )}
            <rect x={x + outerInset} y={cellY + outerInset}
              width={cellW - outerInset * 2} height={cellH - outerInset * 2}
              fill="none" stroke={lineColor} strokeWidth="1.5" />
            <rect x={x + outerInset + innerInset} y={cellY + outerInset + innerInset}
              width={cellW - (outerInset + innerInset) * 2} height={cellH - (outerInset + innerInset) * 2}
              fill="none" stroke={lineColor} strokeWidth="1" />
            <line x1={x + outerInset + innerInset} y1={cellY + cellH - outerInset - innerInset}
              x2={x + cellW - outerInset - innerInset} y2={cellY + cellH - outerInset - innerInset}
              stroke={shadowColor} strokeWidth="2" />
            <line x1={x + cellW - outerInset - innerInset} y1={cellY + outerInset + innerInset}
              x2={x + cellW - outerInset - innerInset} y2={cellY + cellH - outerInset - innerInset}
              stroke={shadowColor} strokeWidth="2" />
            <line x1={x + outerInset + innerInset} y1={cellY + outerInset + innerInset}
              x2={x + cellW - outerInset - innerInset} y2={cellY + outerInset + innerInset}
              stroke={isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.7)'} strokeWidth="1" />
            <line x1={x + outerInset + innerInset} y1={cellY + outerInset + innerInset}
              x2={x + outerInset + innerInset} y2={cellY + cellH - outerInset - innerInset}
              stroke={isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.7)'} strokeWidth="1" />
          </g>
        )
      }
    }
    return panels
  }

  const renderCarriagePanels = (y, w, h, padding, pattern, sectionIndex) => {
    const { rows } = pattern
    const cols = pattern.cols === 'dynamic' ? getStampColumns(width, pattern.stampType, isCraft, panelDesign) : pattern.cols
    const gapX = w * 0.012
    const gapY = h * 0.03
    const cellW = (w - gapX * (cols + 1)) / cols
    const cellH = (h - gapY * (rows + 1)) / rows

    const isLongOnStandard = windowSize === 'long' && pattern.stampType === 'standard'

    const panels = []
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const x = padding + gapX + col * (cellW + gapX)
        const cellY = y + gapY + row * (cellH + gapY)
        const stampKey = `carriage-${sectionIndex}-${row}-${col}`
        const absoluteSection = sectionIndex + 1

        if (isLongOnStandard && col % 2 === 1 && hasWindowAtPosition(absoluteSection, col - 1)) continue

        if (hasWindowAtPosition(absoluteSection, col)) {
          const windowW = isLongOnStandard ? cellW * 2 + gapX : cellW
          panels.push(
            <g key={stampKey}
              style={interactive ? { cursor: 'pointer' } : {}}
              onClick={interactive && onStampClick ? () => onStampClick(absoluteSection, isLongOnStandard ? Math.floor(col / 2) * 2 : col) : undefined}
              onMouseEnter={interactive && onStampHover ? () => onStampHover(absoluteSection, col) : undefined}
              onMouseLeave={interactive && onStampHover ? () => onStampHover(null) : undefined}
            >
              {renderStampWindow(x, cellY, windowW, cellH, col)}
            </g>
          )
          continue
        }

        const outerInset = Math.min(cellW, cellH) * 0.05
        const innerInset = Math.min(cellW, cellH) * 0.12
        const cornerRadius = Math.min(cellW, cellH) * 0.03

        const clickCol = isLongOnStandard ? Math.floor(col / 2) * 2 : col
        const pairStart = isLongOnStandard ? Math.floor(col / 2) * 2 : col
        const isHovered = interactive && highlightStamp &&
          highlightStamp.section === absoluteSection &&
          (isLongOnStandard
            ? Math.floor(highlightStamp.col / 2) * 2 === pairStart
            : highlightStamp.col === col)

        panels.push(
          <g key={stampKey}
            style={interactive ? { cursor: 'pointer' } : {}}
            onClick={interactive && onStampClick ? () => onStampClick(absoluteSection, clickCol) : undefined}
            onMouseEnter={interactive && onStampHover ? () => onStampHover(absoluteSection, col) : undefined}
            onMouseLeave={interactive && onStampHover ? () => onStampHover(null) : undefined}
          >
            {isHovered && (isLongOnStandard ? col % 2 === 0 : true) && (
              <rect x={x} y={cellY}
                width={isLongOnStandard ? cellW * 2 + gapX : cellW} height={cellH}
                fill="rgba(201, 169, 110, 0.2)" stroke="rgba(201, 169, 110, 0.8)"
                strokeWidth="2" strokeDasharray="4,2" rx="2" />
            )}
            <rect x={x + outerInset} y={cellY + outerInset}
              width={cellW - outerInset * 2} height={cellH - outerInset * 2}
              rx={cornerRadius} ry={cornerRadius}
              fill="none" stroke={lineColor} strokeWidth="1.5" />
            <rect x={x + outerInset + innerInset} y={cellY + outerInset + innerInset}
              width={cellW - (outerInset + innerInset) * 2} height={cellH - (outerInset + innerInset) * 2}
              rx={cornerRadius * 0.5} ry={cornerRadius * 0.5}
              fill="none" stroke={lineColor} strokeWidth="1" />
            {(pattern.style === 'bronte') && (() => {
              const innerX = x + outerInset + innerInset
              const innerY2 = cellY + outerInset + innerInset
              const innerW = cellW - (outerInset + innerInset) * 2
              const innerH = cellH - (outerInset + innerInset) * 2
              const numGrooves = Math.max(4, Math.round(innerW / 12))
              const grooveSpacing = innerW / (numGrooves + 1)
              const grooves = []
              for (let g = 1; g <= numGrooves; g++) {
                grooves.push(
                  <line key={`groove-${sectionIndex}-${row}-${col}-${g}`}
                    x1={innerX + grooveSpacing * g} y1={innerY2}
                    x2={innerX + grooveSpacing * g} y2={innerY2 + innerH}
                    stroke={lineColor} strokeWidth="0.75" />
                )
              }
              return grooves
            })()}
            <line x1={x + outerInset + innerInset} y1={cellY + cellH - outerInset - innerInset}
              x2={x + cellW - outerInset - innerInset} y2={cellY + cellH - outerInset - innerInset}
              stroke={shadowColor} strokeWidth="1.5" />
            <line x1={x + cellW - outerInset - innerInset} y1={cellY + outerInset + innerInset}
              x2={x + cellW - outerInset - innerInset} y2={cellY + cellH - outerInset - innerInset}
              stroke={shadowColor} strokeWidth="1.5" />
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
          <line x1={x - 1} y1={y} x2={x - 1} y2={y + h} stroke={shadowColor} strokeWidth="2" />
          <line x1={x} y1={y} x2={x} y2={y + h}
            stroke={isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.6)'} strokeWidth="1" />
        </g>
      )
    }
    return lines
  }

  const renderHorizontalRibbedPanels = (y, w, h, padding, pattern) => {
    const { ribs } = pattern
    const sectionTop = y - padding
    const sectionH = h + padding * 2
    const ribSpacing = sectionH / (ribs + 1)
    const lines = []
    for (let i = 1; i <= ribs; i++) {
      const lineY = sectionTop + ribSpacing * i
      lines.push(
        <g key={`h-rib-${i}`}>
          <line x1={0} y1={lineY - 0.5} x2={displayWidth} y2={lineY - 0.5} stroke={shadowColor} strokeWidth="1" />
          <line x1={0} y1={lineY + 0.5} x2={displayWidth} y2={lineY + 0.5}
            stroke={isDark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.6)'} strokeWidth="0.5" />
        </g>
      )
    }
    return lines
  }

  const renderFlushPanel = (y, w, h, padding) => {
    return <rect x={padding} y={y} width={w} height={h} fill={doorColor} />
  }

  const renderCraftSection = (sectionIndex, sectionY, sectionHeight, pattern) => {
    const padding = displayWidth * 0.02
    const panelWidth = displayWidth - padding * 2
    const panelHeight = sectionHeight - padding * 2
    const stampCount = getStampColumns(width, 'long', true)

    const gapX = panelWidth * 0.015
    const cellW = (panelWidth - gapX * (stampCount + 1)) / stampCount

    if (sectionIndex === 0) {
      const elements = []
      elements.push(
        <rect key="craft-top-flush"
          x={padding} y={sectionY + padding}
          width={panelWidth} height={panelHeight}
          fill={doorColor} />
      )
      const windowInset = panelHeight * 0.1
      const windowH = panelHeight - windowInset * 2
      const windowGapInner = cellW * 0.06

      for (let i = 0; i < stampCount; i++) {
        const wx = padding + gapX + i * (cellW + gapX) + windowGapInner
        const wy = sectionY + padding + windowInset
        const windowW = cellW - windowGapInner * 2
        const frameW = 2.5
        const dividerColor = resolvedFrame.stroke
        elements.push(
          <rect key={`craft-win-frame-${i}`}
            x={wx - frameW} y={wy - frameW}
            width={windowW + frameW * 2} height={windowH + frameW * 2}
            fill={resolvedFrame.fill} stroke={resolvedFrame.stroke}
            strokeWidth="1" rx="1" />
        )
        elements.push(
          <rect key={`craft-win-glass-${i}`}
            x={wx} y={wy} width={windowW} height={windowH}
            fill="#87CEEB" stroke="#666" strokeWidth="0.5" />
        )
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
        elements.push(
          <rect key={`craft-win-refl-${i}`}
            x={wx + 3} y={wy + 3}
            width={windowW * 0.18} height={windowH * 0.22}
            fill={`url(#glassReflection-${instanceId})`} opacity="0.3" />
        )
      }
      return elements
    }

    const cellH = panelHeight
    const cellY = sectionY + padding
    const recessFill = isDark ? 'rgba(0,0,0,0.15)' : 'rgba(0,0,0,0.06)'

    const panels = []
    for (let col = 0; col < stampCount; col++) {
      const x = padding + gapX + col * (cellW + gapX)
      const cellKey = `craft-${sectionIndex}-${col}`

      if (pattern.type === 'xbrace') {
        const cx = x + cellW / 2
        const bw = Math.max(6, Math.min(cellW, cellH) * 0.09)
        const hw = bw / 2
        const diagLen = Math.sqrt((cellW / 2) ** 2 + cellH ** 2)
        const offH = hw * diagLen / cellH
        const offV = 2 * hw * diagLen / cellW

        let triPaths
        if (sectionIndex === 1) {
          const t1 = `M ${x + offH},${cellY} L ${x + cellW - offH},${cellY} L ${cx},${cellY + cellH - offV} Z`
          const t2 = `M ${x},${cellY + offV} L ${x},${cellY + cellH} L ${cx - offH},${cellY + cellH} Z`
          const t3 = `M ${x + cellW},${cellY + offV} L ${x + cellW},${cellY + cellH} L ${cx + offH},${cellY + cellH} Z`
          triPaths = [t1, t2, t3]
        } else {
          const t1 = `M ${x + offH},${cellY + cellH} L ${x + cellW - offH},${cellY + cellH} L ${cx},${cellY + offV} Z`
          const t2 = `M ${x},${cellY + cellH - offV} L ${x},${cellY} L ${cx - offH},${cellY} Z`
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
        els.push(
          <rect key={`${cellKey}-border`} x={ix} y={iy} width={iw} height={ih}
            fill="none" stroke={lineColor} strokeWidth="1.5" />
        )
        for (let c = 0; c < gridCols; c++) {
          const sx = ix + gap + c * (subW + gap)
          const sy = iy + gap
          els.push(
            <rect key={`${cellKey}-fill-${c}`} x={sx} y={sy} width={subW} height={subH}
              fill={recessFill} stroke="none" />
          )
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

  const renderDimensions = () => {
    if (!showDimensions) return null
    const widthFt = Math.floor(width / 12)
    const widthIn = width % 12
    const heightFt = Math.floor(height / 12)
    const heightIn = height % 12
    const widthLabel = widthIn > 0 ? `${widthFt}'-${widthIn}"` : `${widthFt}'-0"`
    const heightLabel = heightIn > 0 ? `${heightFt}'-${heightIn}"` : `${heightFt}'-0"`

    return (
      <g className="dimensions" fontFamily="Arial, sans-serif" fontSize="12" fill="#999">
        <g transform={`translate(0, ${displayHeight + 25})`}>
          <line x1="0" y1="0" x2={displayWidth} y2="0" stroke="#666" strokeWidth="1" />
          <line x1="0" y1="-5" x2="0" y2="5" stroke="#666" strokeWidth="1" />
          <line x1={displayWidth} y1="-5" x2={displayWidth} y2="5" stroke="#666" strokeWidth="1" />
          <text x={displayWidth / 2} y="15" textAnchor="middle" fontWeight="bold">{widthLabel}</text>
        </g>
        <g transform={`translate(${displayWidth + 15}, 0)`}>
          <line x1="0" y1="0" x2="0" y2={displayHeight} stroke="#666" strokeWidth="1" />
          <line x1="-5" y1="0" x2="5" y2="0" stroke="#666" strokeWidth="1" />
          <line x1="-5" y1={displayHeight} x2="5" y2={displayHeight} stroke="#666" strokeWidth="1" />
          <text x="15" y={displayHeight / 2} textAnchor="middle" fontWeight="bold"
            transform={`rotate(90, 15, ${displayHeight / 2})`}>{heightLabel}</text>
        </g>
      </g>
    )
  }

  let currentY = 0
  const sections = sectionConfig.map((sectionHeight, index) => {
    const scaledHeight = (sectionHeight * sectionHeightScale / height) * displayHeight
    const sectionY = currentY
    currentY += scaledHeight
    return { index, y: sectionY, height: scaledHeight, originalHeight: sectionHeight }
  })

  return (
    <div className="odc-door-preview" style={{ display: 'inline-block' }}>
      <svg
        width={displayWidth + (showDimensions ? 50 : 0)}
        height={displayHeight + (showDimensions ? 45 : 0)}
        viewBox={`0 0 ${displayWidth + (showDimensions ? 50 : 0)} ${displayHeight + (showDimensions ? 45 : 0)}`}
      >
        <defs>
          <linearGradient id={`glassReflection-${instanceId}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="white" stopOpacity="0.6" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </linearGradient>
          <filter id={`doorShadow-${instanceId}`} x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="3" dy="3" stdDeviation="4" floodOpacity="0.3"/>
          </filter>
          {isWoodgrain(color) && WOODGRAIN_COLORS[color] && (
            <pattern id={`woodgrainPattern-${instanceId}`} patternUnits="userSpaceOnUse" width="100" height="8">
              <rect width="100" height="8" fill={WOODGRAIN_COLORS[color].base} />
              <path d={`M0,2 Q25,0 50,2 T100,2`}
                stroke={WOODGRAIN_COLORS[color].dark} strokeWidth="0.5" fill="none" opacity="0.6" />
              <path d={`M0,5 Q30,3 60,5 T100,5`}
                stroke={WOODGRAIN_COLORS[color].light} strokeWidth="0.3" fill="none" opacity="0.4" />
              <path d={`M0,7 Q20,6 40,7 T80,6.5 T100,7`}
                stroke={WOODGRAIN_COLORS[color].dark} strokeWidth="0.4" fill="none" opacity="0.5" />
            </pattern>
          )}
        </defs>

        <rect x="0" y="0" width={displayWidth} height={displayHeight}
          fill={isWoodgrain(color) ? `url(#woodgrainPattern-${instanceId})` : doorColor}
          stroke="#333" strokeWidth="2"
          filter={`url(#doorShadow-${instanceId})`} />

        {sections.map((section) => (
          <g key={`section-${section.index}`}>
            {section.index > 0 && (
              <line x1="0" y1={section.y} x2={displayWidth} y2={section.y}
                stroke={lineColor} strokeWidth="2" />
            )}
            {renderPanelDesign(section.index, section.y, section.height)}
          </g>
        ))}

        <rect x="0" y="0" width={displayWidth} height={displayHeight}
          fill="none" stroke="#333" strokeWidth="3" />

        {renderDimensions()}
      </svg>
    </div>
  )
}

export default DoorPreview
