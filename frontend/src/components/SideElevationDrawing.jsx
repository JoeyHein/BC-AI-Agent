/**
 * SideElevationDrawing Component
 * Renders a professional architectural side elevation view of a garage door installation,
 * closely matching Thermalex shop drawing style.
 * Supports standard, high_lift, vertical, lhr_front, lhr_rear lift types.
 * Uses exact Thermalex geometry from the backend when available.
 *
 * All visual sizes (fonts, ticks, margins, spacing) are proportional to the drawing
 * size via a baseUnit derived from door dimensions, so large doors (e.g. 16'x16')
 * don't suffer from overlapping labels.
 */

import { useMemo } from 'react'

/**
 * Format inches to architectural feet-inches notation.
 * Examples: 96 -> 8'-0", 90 -> 7'-6", 15.75 -> 15.75", 0 -> 0"
 */
function formatDim(inches) {
  if (inches == null || isNaN(inches)) return '0"'
  const abs = Math.abs(inches)
  const ft = Math.floor(abs / 12)
  const rem = abs - ft * 12
  const isWhole = Math.abs(rem - Math.round(rem)) < 0.001
  const inStr = isWhole ? `${Math.round(rem)}` : `${rem}`
  if (ft === 0) return `${inStr}"`
  if (Math.round(rem * 100) === 0) return `${ft}'-0"`
  return `${ft}'-${inStr}"`
}

function SideElevationDrawing({
  width = 96,
  height = 84,
  trackRadius = 15,
  trackSize = 2,
  liftType = 'standard',
  highLiftInches = null,
  geometry = null,
  doorSeries = '',
  doorType = 'residential',
  scale = 0.5,
  title = 'SIDE ELEVATION',
}) {
  const g = useMemo(() => {
    const geo = geometry || {}

    const doorH = geo.door_height || height
    const doorW = geo.door_width || width
    const radius = geo.track_radius || trackRadius
    const tSize = geo.track_size || trackSize
    const hl = geo.high_lift_inches ?? highLiftInches ?? 0
    const lift = geo.lift_type || liftType

    let headroomMin, backroom, sideroom, ust, clShaft
    let verticalTrackLen, horizontalTrackLen
    let curveType, trackTypeLabel, radiusLabel, liftLabel

    if (geometry) {
      headroomMin = geo.headroom_min
      backroom = geo.backroom
      sideroom = geo.sideroom || 4.25
      ust = geo.ust
      clShaft = geo.cl_shaft
      verticalTrackLen = geo.vertical_track_length || doorH
      horizontalTrackLen = geo.horizontal_track_length || 0
      curveType = geo.curve_type || 'quarter'
      trackTypeLabel = geo.track_type_label || ''
      radiusLabel = geo.radius_label || `${radius}" RADIUS`
      liftLabel = geo.lift_label || lift.replace(/_/g, ' ').toUpperCase()
    } else {
      switch (lift) {
        case 'lhr_front':
          headroomMin = 10
          backroom = doorH + 18 + 6
          sideroom = 4.25
          ust = 5
          clShaft = 7
          verticalTrackLen = doorH
          horizontalTrackLen = doorH + 18
          curveType = 'low_headroom'
          break
        case 'lhr_rear':
          headroomMin = 5.5
          backroom = doorH + 18 + 6
          sideroom = 4.25
          ust = 3
          clShaft = 4.5
          verticalTrackLen = doorH
          horizontalTrackLen = doorH + 18
          curveType = 'low_headroom'
          break
        case 'high_lift':
          headroomMin = hl + radius + 3
          backroom = doorH - hl + 30
          sideroom = 4.25
          ust = hl + radius + 1.5
          clShaft = hl + radius + 6
          verticalTrackLen = doorH + hl
          horizontalTrackLen = doorH - hl + 18
          curveType = 'quarter'
          break
        case 'vertical':
          headroomMin = doorH + 18
          backroom = 18
          sideroom = 4.25
          ust = doorH + 12
          clShaft = doorH + 14.5
          verticalTrackLen = doorH * 2 + 6
          horizontalTrackLen = 0
          curveType = 'none'
          break
        default: // standard
          headroomMin = radius + 3
          backroom = doorH + 18 + 6
          sideroom = 4.25
          ust = radius + 1.5
          clShaft = radius + 6
          verticalTrackLen = doorH
          horizontalTrackLen = doorH + 18
          curveType = 'quarter'
      }
      trackTypeLabel = `${lift.replace(/_/g, ' ').toUpperCase()} LIFT TRACKS`
      radiusLabel = `${radius}" RADIUS`
      liftLabel = lift.replace(/_/g, ' ').toUpperCase()
    }

    return {
      doorH, doorW, radius, tSize, hl, lift,
      headroomMin, backroom, sideroom, ust, clShaft,
      verticalTrackLen, horizontalTrackLen,
      curveType, trackTypeLabel, radiusLabel, liftLabel,
    }
  }, [width, height, trackRadius, trackSize, liftType, highLiftInches, geometry])

  // --- Proportional base unit ---
  const baseUnit = Math.max(5, Math.min(12, Math.sqrt(g.doorH * scale) * 0.8))

  // Font sizes — monospace technical drawing style
  const fontTitle = baseUnit * 1.6
  const fontSubtitle = baseUnit * 1.2
  const fontLabel = baseUnit
  const fontSmall = baseUnit * 0.8
  const fontTiny = baseUnit * 0.65

  // Dimension helpers
  const tickLen = baseUnit * 0.6 // length of 45-degree tick slash

  // Margins scale with content
  const MARGIN_LEFT = Math.max(90, baseUnit * 11)
  const MARGIN_RIGHT = Math.max(90, baseUnit * 11)
  const MARGIN_TOP = Math.max(60, baseUnit * 8)
  const MARGIN_BOTTOM = Math.max(110, baseUnit * 13)

  const WALL_THICKNESS = 8
  const WALL_DRAW_W = 16
  const DOOR_THICKNESS = 4
  const HEADER_DEPTH = 6 // inches for header beam thickness

  // Scaling helper: inches to pixels
  const s = (inches) => inches * scale

  // Compute drawing extents
  const layout = useMemo(() => {
    const aboveDoor = Math.max(g.headroomMin, g.clShaft + 8)
    const minAbovePx = 140
    const aboveDoorPx = Math.max(minAbovePx, s(aboveDoor))
    const totalHorizontal = WALL_THICKNESS + g.backroom + 16

    const contentW = s(totalHorizontal)
    const rawW = MARGIN_LEFT + contentW + MARGIN_RIGHT
    const svgW = Math.max(520, rawW)
    const svgH = MARGIN_TOP + aboveDoorPx + s(g.doorH) + MARGIN_BOTTOM

    const originX = MARGIN_LEFT + WALL_DRAW_W
    const originY = MARGIN_TOP + aboveDoorPx

    return { svgW, svgH, originX, originY, aboveDoor, aboveDoorPx, contentW }
  }, [g, scale, MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM])

  const { svgW, svgH, originX, originY } = layout

  const floorY = originY + s(g.doorH)
  const curveStartY = originY - (g.lift === 'high_lift' ? s(g.hl) : 0)
  const horizontalTrackEndX = originX + s(g.backroom)
  const shaftY = originY - s(g.clShaft)
  const ustY = originY - s(g.ust)

  // Panel count for drawing
  const panelCount = Math.round(g.doorH / 21) || 4
  const panelH = g.doorH / panelCount

  /**
   * Draw a 45-degree diagonal tick mark at a point on a dimension line.
   * For vertical dimension lines, the tick is a short diagonal slash.
   * For horizontal dimension lines, the tick is also a short diagonal slash.
   */
  function DiagTick({ x, y, size = tickLen }) {
    const half = size / 2
    return (
      <line
        x1={x - half} y1={y + half}
        x2={x + half} y2={y - half}
        stroke="#000" strokeWidth="0.75"
      />
    )
  }

  return (
    <div className="side-elevation-drawing bg-white border border-gray-300 rounded-lg overflow-hidden">
      <svg
        viewBox={`0 0 ${svgW} ${svgH}`}
        style={{ fontFamily: "'Courier New', 'Lucida Console', monospace", maxWidth: `${svgW}px`, width: '100%' }}
      >
        <defs>
          {/* Cross-hatch pattern 1 (45 degrees) */}
          <pattern id="sideHatch45" patternUnits="userSpaceOnUse" width="5" height="5" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="5" stroke="#555" strokeWidth="0.4" />
          </pattern>
          {/* Cross-hatch pattern 2 (-45 degrees) */}
          <pattern id="sideHatch135" patternUnits="userSpaceOnUse" width="5" height="5" patternTransform="rotate(-45)">
            <line x1="0" y1="0" x2="0" y2="5" stroke="#555" strokeWidth="0.4" />
          </pattern>
          {/* Insulation pattern for panel callout */}
          <pattern id="insulFill" patternUnits="userSpaceOnUse" width="12" height="8">
            <path d="M0,4 Q3,0 6,4 Q9,8 12,4" fill="none" stroke="#999" strokeWidth="0.5" />
          </pattern>
        </defs>

        {/* ===== TITLE ===== */}
        <text x={svgW / 2} y={fontTitle + 4} fontSize={fontTitle} fontWeight="bold" textAnchor="middle" fill="#000" letterSpacing="2">
          {title}
        </text>
        <text x={svgW / 2} y={fontTitle + 4 + fontSubtitle + 6} fontSize={fontSubtitle} textAnchor="middle" fill="#000" letterSpacing="1">
          {g.trackTypeLabel}
        </text>
        {doorSeries && (
          <text x={svgW / 2} y={fontTitle + 4 + fontSubtitle + 6 + fontLabel + 4} fontSize={fontSmall} textAnchor="middle" fill="#333">
            {doorSeries} | {doorType.toUpperCase()}
          </text>
        )}

        {/* ===== FLOOR LINE ===== */}
        <line
          x1={originX - WALL_DRAW_W - 25}
          y1={floorY}
          x2={originX + s(g.backroom) + 40}
          y2={floorY}
          stroke="#000"
          strokeWidth="2.5"
        />
        {/* Ground hatching below floor */}
        {Array.from({ length: Math.ceil((s(g.backroom) + WALL_DRAW_W + 65) / 7) }, (_, i) => (
          <line
            key={`gh${i}`}
            x1={originX - WALL_DRAW_W - 25 + i * 7}
            y1={floorY + 2}
            x2={originX - WALL_DRAW_W - 25 + i * 7 - 5}
            y2={floorY + 7}
            stroke="#555"
            strokeWidth="0.5"
          />
        ))}
        {/* FLOOR LINE label */}
        <text
          x={originX + s(g.backroom / 2)}
          y={floorY + baseUnit * 1.4}
          fontSize={fontTiny}
          fill="#333"
          textAnchor="middle"
          letterSpacing="1"
        >
          FLOOR LINE
        </text>

        {/* ===== WALL / HEADER SECTION ===== */}
        {/* Wall extends from well above header to below floor */}
        {(() => {
          const wallTop = originY - s(g.headroomMin + 24)
          const wallBottom = floorY + 16
          const wallH = wallBottom - wallTop
          return (
            <g className="wall-section">
              {/* First hatch layer */}
              <rect
                x={originX - WALL_DRAW_W} y={wallTop}
                width={WALL_DRAW_W} height={wallH}
                fill="url(#sideHatch45)" stroke="none"
              />
              {/* Second hatch layer (cross pattern) */}
              <rect
                x={originX - WALL_DRAW_W} y={wallTop}
                width={WALL_DRAW_W} height={wallH}
                fill="url(#sideHatch135)" stroke="none"
              />
              {/* Wall outline */}
              <rect
                x={originX - WALL_DRAW_W} y={wallTop}
                width={WALL_DRAW_W} height={wallH}
                fill="none" stroke="#000" strokeWidth="1.5"
              />

              {/* Header beam — thick structural element above the opening */}
              <rect
                x={originX - WALL_DRAW_W} y={originY - s(HEADER_DEPTH)}
                width={WALL_DRAW_W + s(6)} height={s(HEADER_DEPTH)}
                fill="url(#sideHatch45)" stroke="none"
              />
              <rect
                x={originX - WALL_DRAW_W} y={originY - s(HEADER_DEPTH)}
                width={WALL_DRAW_W + s(6)} height={s(HEADER_DEPTH)}
                fill="url(#sideHatch135)" stroke="none"
              />
              <rect
                x={originX - WALL_DRAW_W} y={originY - s(HEADER_DEPTH)}
                width={WALL_DRAW_W + s(6)} height={s(HEADER_DEPTH)}
                fill="none" stroke="#000" strokeWidth="2"
              />

              {/* Clear opening line at top of door */}
              <line
                x1={originX} y1={originY}
                x2={originX + s(12)} y2={originY}
                stroke="#000" strokeWidth="1"
              />
            </g>
          )
        })()}

        {/* ===== EXTERIOR / INTERIOR LABELS ===== */}
        <text
          x={originX - WALL_DRAW_W - baseUnit * 1.5}
          y={originY + s(g.doorH / 2)}
          fontSize={fontLabel}
          fill="#000"
          textAnchor="middle"
          transform={`rotate(-90, ${originX - WALL_DRAW_W - baseUnit * 1.5}, ${originY + s(g.doorH / 2)})`}
          fontWeight="bold"
          letterSpacing="2"
        >
          EXTERIOR
        </text>
        <text
          x={originX + s(g.backroom / 2)}
          y={floorY + baseUnit * 2.8}
          fontSize={fontLabel}
          fill="#000"
          textAnchor="middle"
          fontWeight="bold"
          letterSpacing="2"
        >
          INTERIOR
        </text>

        {/* ===== CEILING LINE (dashed) ===== */}
        <line
          x1={originX}
          y1={originY - s(g.headroomMin)}
          x2={originX + s(g.backroom) + 30}
          y2={originY - s(g.headroomMin)}
          stroke="#000"
          strokeWidth="0.75"
          strokeDasharray="8,4"
        />
        <text
          x={originX + s(g.backroom) + 32}
          y={originY - s(g.headroomMin) + fontTiny * 0.35}
          fontSize={fontTiny}
          fill="#333"
          textAnchor="start"
        >
          CEILING
        </text>

        {/* ===== DOOR IN CLOSED POSITION ===== */}
        <rect
          x={originX}
          y={originY}
          width={s(DOOR_THICKNESS)}
          height={s(g.doorH)}
          fill="#e8e8e8"
          stroke="#000"
          strokeWidth="1.5"
        />
        {/* Panel lines on closed door */}
        {Array.from({ length: panelCount - 1 }, (_, i) => {
          const py = originY + s(panelH * (i + 1))
          return (
            <line
              key={`panel${i}`}
              x1={originX}
              y1={py}
              x2={originX + s(DOOR_THICKNESS)}
              y2={py}
              stroke="#666"
              strokeWidth="0.75"
            />
          )
        })}
        {/* Roller indicators at panel joints */}
        {Array.from({ length: panelCount - 1 }, (_, i) => {
          const py = originY + s(panelH * (i + 1))
          const rollerX = originX + s(DOOR_THICKNESS) + s(1.5)
          return (
            <circle
              key={`roller${i}`}
              cx={rollerX}
              cy={py}
              r={baseUnit * 0.25}
              fill="none"
              stroke="#000"
              strokeWidth="0.75"
            />
          )
        })}
        {/* DOOR (CLOSED) label */}
        <text
          x={originX + s(DOOR_THICKNESS / 2)}
          y={originY + s(g.doorH / 2)}
          fontSize={fontSmall}
          fill="#333"
          textAnchor="middle"
          transform={`rotate(-90, ${originX + s(DOOR_THICKNESS / 2)}, ${originY + s(g.doorH / 2)})`}
          letterSpacing="0.5"
        >
          DOOR (CLOSED)
        </text>

        {/* ===== TRACKS AND DOOR OPEN POSITION ===== */}
        {renderTracks()}
        {renderDoorOpen()}
        {renderShaftAssembly()}

        {/* ===== DIMENSION LINES ===== */}
        {renderDimensions()}

        {/* ===== PANEL CROSS-SECTION CALLOUT ===== */}
        {renderPanelCallout()}

        {/* ===== REQUIREMENTS BOX ===== */}
        {renderRequirementsBox()}

        {/* ===== TITLE BLOCK (bottom-right corner) ===== */}
        {renderTitleBlock()}
      </svg>
    </div>
  )

  /**
   * Render track system based on lift type
   */
  function renderTracks() {
    const elements = []
    const lift = g.lift

    if (lift === 'vertical') {
      const trackX1 = originX + s(DOOR_THICKNESS + 1)
      const trackX2 = originX + s(DOOR_THICKNESS + 1 + g.tSize)
      const trackTop = originY - s(g.verticalTrackLen - g.doorH)
      elements.push(
        <g key="vert-tracks">
          <line x1={trackX1} y1={floorY} x2={trackX1} y2={trackTop}
            stroke="#000" strokeWidth="1.5" />
          <line x1={trackX2} y1={floorY} x2={trackX2} y2={trackTop}
            stroke="#000" strokeWidth="1.5" />
          {/* U-turn at top */}
          <path
            d={`M ${trackX1} ${trackTop} A ${s(g.tSize / 2)} ${s(3)} 0 0 1 ${trackX2} ${trackTop}`}
            fill="none" stroke="#000" strokeWidth="1"
          />
          <text
            x={trackX2 + baseUnit}
            y={originY - s((g.verticalTrackLen - g.doorH) / 2)}
            fontSize={fontTiny}
            fill="#333"
            textAnchor="start"
            transform={`rotate(-90, ${trackX2 + baseUnit}, ${originY - s((g.verticalTrackLen - g.doorH) / 2)})`}
            letterSpacing="0.5"
          >
            VERTICAL TRACK
          </text>
        </g>
      )
    } else if (lift === 'lhr_front' || lift === 'lhr_rear') {
      const trackOffset = s(g.tSize + 2)
      elements.push(
        <g key="lhr-tracks">
          {/* Inner vertical track */}
          <line x1={originX + s(DOOR_THICKNESS + 1)} y1={floorY}
            x2={originX + s(DOOR_THICKNESS + 1)} y2={originY}
            stroke="#000" strokeWidth="1" />
          <line x1={originX + s(DOOR_THICKNESS + 1 + g.tSize)} y1={floorY}
            x2={originX + s(DOOR_THICKNESS + 1 + g.tSize)} y2={originY}
            stroke="#000" strokeWidth="1" />
          {/* Outer vertical track */}
          <line x1={originX + s(DOOR_THICKNESS + 1) + trackOffset} y1={floorY}
            x2={originX + s(DOOR_THICKNESS + 1) + trackOffset} y2={originY}
            stroke="#000" strokeWidth="1" />
          <line x1={originX + s(DOOR_THICKNESS + 1 + g.tSize) + trackOffset} y1={floorY}
            x2={originX + s(DOOR_THICKNESS + 1 + g.tSize) + trackOffset} y2={originY}
            stroke="#000" strokeWidth="1" />
          {/* Inner horizontal track */}
          <line x1={originX + s(DOOR_THICKNESS + 1)} y1={originY - s(g.headroomMin - 2)}
            x2={horizontalTrackEndX} y2={originY - s(g.headroomMin - 2)}
            stroke="#000" strokeWidth="1" />
          <line x1={originX + s(DOOR_THICKNESS + 1)} y1={originY - s(g.headroomMin - 2 - g.tSize)}
            x2={horizontalTrackEndX} y2={originY - s(g.headroomMin - 2 - g.tSize)}
            stroke="#000" strokeWidth="1" />
          {/* Outer horizontal track */}
          <line x1={originX + s(DOOR_THICKNESS + 1) + trackOffset} y1={originY - s(g.headroomMin - 2)}
            x2={horizontalTrackEndX} y2={originY - s(g.headroomMin - 2)}
            stroke="#000" strokeWidth="1" />
          <line x1={originX + s(DOOR_THICKNESS + 1) + trackOffset} y1={originY - s(g.headroomMin - 2 - g.tSize)}
            x2={horizontalTrackEndX} y2={originY - s(g.headroomMin - 2 - g.tSize)}
            stroke="#000" strokeWidth="1" />
          {/* End stop */}
          <line x1={horizontalTrackEndX} y1={originY - s(g.headroomMin - 2) - 4}
            x2={horizontalTrackEndX} y2={originY - s(g.headroomMin - 2 - g.tSize) + 4}
            stroke="#000" strokeWidth="2" />
          {/* LHR label */}
          <text
            x={originX + s(g.backroom / 2)}
            y={originY - s(g.headroomMin) - baseUnit * 0.8}
            fontSize={fontTiny}
            fill="#333"
            textAnchor="middle"
            letterSpacing="0.5"
          >
            {lift === 'lhr_front' ? 'LOW HEADROOM FRONT MOUNT' : 'LOW HEADROOM REAR MOUNT'}
          </text>
        </g>
      )
    } else {
      // Standard and High Lift
      const vtTop = lift === 'high_lift' ? originY - s(g.hl) : originY

      elements.push(
        <g key="std-tracks">
          {/* Vertical track — two parallel lines */}
          <line x1={originX + s(DOOR_THICKNESS + 1)} y1={floorY}
            x2={originX + s(DOOR_THICKNESS + 1)} y2={vtTop}
            stroke="#000" strokeWidth="1" />
          <line x1={originX + s(DOOR_THICKNESS + 1 + g.tSize)} y1={floorY}
            x2={originX + s(DOOR_THICKNESS + 1 + g.tSize)} y2={vtTop}
            stroke="#000" strokeWidth="1" />

          {/* High lift extra vertical section */}
          {lift === 'high_lift' && g.hl > 0 && (
            <g key="hl-section">
              <line x1={originX + s(DOOR_THICKNESS + 1)} y1={originY}
                x2={originX + s(DOOR_THICKNESS + 1)} y2={vtTop}
                stroke="#000" strokeWidth="1.5" />
              <line x1={originX + s(DOOR_THICKNESS + 1 + g.tSize)} y1={originY}
                x2={originX + s(DOOR_THICKNESS + 1 + g.tSize)} y2={vtTop}
                stroke="#000" strokeWidth="1.5" />
              <text
                x={originX + s(DOOR_THICKNESS + 1 + g.tSize + 3)}
                y={originY - s(g.hl / 2)}
                fontSize={fontTiny}
                fill="#000"
                textAnchor="start"
                transform={`rotate(-90, ${originX + s(DOOR_THICKNESS + 1 + g.tSize + 3)}, ${originY - s(g.hl / 2)})`}
                letterSpacing="0.5"
              >
                HIGH LIFT {formatDim(g.hl)}
              </text>
            </g>
          )}

          {/* Quarter-circle curve */}
          {g.curveType !== 'none' && (
            <g key="curve">
              {/* Outer curve */}
              <path
                d={`M ${originX + s(DOOR_THICKNESS + 1)} ${vtTop}
                    A ${s(g.radius)} ${s(g.radius)} 0 0 0
                    ${originX + s(DOOR_THICKNESS + 1 + g.radius)} ${vtTop - s(g.radius)}`}
                fill="none"
                stroke="#000"
                strokeWidth="1"
              />
              {/* Inner curve */}
              <path
                d={`M ${originX + s(DOOR_THICKNESS + 1 + g.tSize)} ${vtTop}
                    A ${s(g.radius - g.tSize)} ${s(g.radius - g.tSize)} 0 0 0
                    ${originX + s(DOOR_THICKNESS + 1 + g.radius)} ${vtTop - s(g.radius - g.tSize)}`}
                fill="none"
                stroke="#000"
                strokeWidth="1"
              />
              {/* Radius label */}
              <text
                x={originX + s(DOOR_THICKNESS + 1 + g.radius * 0.35)}
                y={vtTop - s(g.radius * 0.4) - baseUnit * 0.3}
                fontSize={fontTiny}
                fill="#333"
                letterSpacing="0.5"
              >
                {g.radiusLabel}
              </text>
            </g>
          )}

          {/* Horizontal track */}
          {g.horizontalTrackLen > 0 && (
            <g key="horiz-track">
              {/* Top rail */}
              <line
                x1={originX + s(DOOR_THICKNESS + 1 + g.radius)}
                y1={vtTop - s(g.radius)}
                x2={horizontalTrackEndX}
                y2={vtTop - s(g.radius)}
                stroke="#000"
                strokeWidth="1"
              />
              {/* Bottom rail */}
              <line
                x1={originX + s(DOOR_THICKNESS + 1 + g.radius)}
                y1={vtTop - s(g.radius - g.tSize)}
                x2={horizontalTrackEndX}
                y2={vtTop - s(g.radius - g.tSize)}
                stroke="#000"
                strokeWidth="1"
              />
              {/* End stop */}
              <line
                x1={horizontalTrackEndX}
                y1={vtTop - s(g.radius) - 4}
                x2={horizontalTrackEndX}
                y2={vtTop - s(g.radius - g.tSize) + 4}
                stroke="#000"
                strokeWidth="2"
              />
            </g>
          )}
        </g>
      )
    }

    return <g className="tracks">{elements}</g>
  }

  /**
   * Render door in open position (dashed lines)
   */
  function renderDoorOpen() {
    const lift = g.lift

    if (lift === 'vertical') {
      return (
        <g className="door-open">
          <rect
            x={originX}
            y={originY - s(g.doorH) - 4}
            width={s(DOOR_THICKNESS)}
            height={s(g.doorH)}
            fill="none"
            stroke="#000"
            strokeWidth="0.75"
            strokeDasharray="6,3"
          />
          <text
            x={originX + s(DOOR_THICKNESS / 2)}
            y={originY - s(g.doorH / 2)}
            fontSize={fontTiny}
            fill="#333"
            textAnchor="middle"
            transform={`rotate(-90, ${originX + s(DOOR_THICKNESS / 2)}, ${originY - s(g.doorH / 2)})`}
            letterSpacing="0.5"
          >
            DOOR (OPEN)
          </text>
        </g>
      )
    }

    if (lift === 'lhr_front' || lift === 'lhr_rear') {
      const openY = originY - s(g.headroomMin - 2)
      return (
        <g className="door-open">
          <rect
            x={originX + s(6)}
            y={openY - s(DOOR_THICKNESS)}
            width={s(g.doorH)}
            height={s(DOOR_THICKNESS)}
            fill="none"
            stroke="#000"
            strokeWidth="0.75"
            strokeDasharray="6,3"
          />
          <text
            x={originX + s(6 + g.doorH / 2)}
            y={openY - s(DOOR_THICKNESS) - baseUnit * 0.4}
            fontSize={fontTiny}
            fill="#333"
            textAnchor="middle"
            letterSpacing="0.5"
          >
            DOOR (OPEN)
          </text>
        </g>
      )
    }

    // Standard / High Lift
    const vtTop = lift === 'high_lift' ? originY - s(g.hl) : originY
    const trackCenterY = vtTop - s(g.radius - g.tSize / 2)

    return (
      <g className="door-open">
        <rect
          x={originX + s(DOOR_THICKNESS + 1 + g.radius)}
          y={trackCenterY - s(DOOR_THICKNESS / 2)}
          width={s(g.doorH)}
          height={s(DOOR_THICKNESS)}
          fill="none"
          stroke="#000"
          strokeWidth="0.75"
          strokeDasharray="6,3"
        />
        {/* Panel lines in open door */}
        {Array.from({ length: panelCount - 1 }, (_, i) => {
          const px = originX + s(DOOR_THICKNESS + 1 + g.radius + panelH * (i + 1))
          return (
            <line
              key={`opanel${i}`}
              x1={px}
              y1={trackCenterY - s(DOOR_THICKNESS / 2)}
              x2={px}
              y2={trackCenterY + s(DOOR_THICKNESS / 2)}
              stroke="#999"
              strokeWidth="0.5"
              strokeDasharray="3,2"
            />
          )
        })}
        <text
          x={originX + s(DOOR_THICKNESS + 1 + g.radius + g.doorH / 2)}
          y={trackCenterY}
          fontSize={fontTiny}
          fill="#333"
          textAnchor="middle"
          dominantBaseline="middle"
          letterSpacing="0.5"
        >
          DOOR (OPEN)
        </text>
      </g>
    )
  }

  /**
   * Render torsion shaft, drum, springs, and cable
   */
  function renderShaftAssembly() {
    const lift = g.lift
    const drumR = s(3)

    if (lift === 'lhr_front' || lift === 'lhr_rear') {
      const sy = originY - s(g.headroomMin - 3)
      return (
        <g className="shaft-assembly">
          {/* Shaft line */}
          <line x1={originX + s(2)} y1={sy} x2={originX + s(20)} y2={sy}
            stroke="#000" strokeWidth="2" />
          {/* Drum circle */}
          <circle cx={originX + s(6)} cy={sy} r={drumR}
            fill="none" stroke="#000" strokeWidth="1" />
          {/* X inside drum */}
          <line x1={originX + s(6) - drumR * 0.6} y1={sy - drumR * 0.6}
            x2={originX + s(6) + drumR * 0.6} y2={sy + drumR * 0.6}
            stroke="#000" strokeWidth="0.5" />
          <line x1={originX + s(6) + drumR * 0.6} y1={sy - drumR * 0.6}
            x2={originX + s(6) - drumR * 0.6} y2={sy + drumR * 0.6}
            stroke="#000" strokeWidth="0.5" />
          {/* Spring coils (zigzag) */}
          <path
            d={generateSpringPath(originX + s(8), sy, originX + s(18), 12)}
            fill="none" stroke="#000" strokeWidth="1"
          />
          {/* Cable from drum to bottom bracket */}
          <line x1={originX + s(6)} y1={sy + drumR}
            x2={originX + s(4)} y2={floorY - s(4)}
            stroke="#000" strokeWidth="0.75" strokeDasharray="4,2" />
          {/* Bottom bracket */}
          <rect
            x={originX + s(DOOR_THICKNESS) - 1}
            y={floorY - s(6)}
            width={4} height={s(4)}
            fill="#000" stroke="#000" strokeWidth="0.5"
          />
          <text x={originX + s(13)} y={sy - baseUnit * 0.6} fontSize={fontTiny} fill="#333" textAnchor="middle" letterSpacing="0.5">
            SHAFT &amp; SPRING
          </text>
        </g>
      )
    }

    return (
      <g className="shaft-assembly">
        {/* Shaft line */}
        <line
          x1={originX + s(2)}
          y1={shaftY}
          x2={originX + s(22)}
          y2={shaftY}
          stroke="#000"
          strokeWidth="2"
        />
        {/* Drum circle with X cross inside */}
        <circle
          cx={originX + s(6)}
          cy={shaftY}
          r={drumR}
          fill="none"
          stroke="#000"
          strokeWidth="1"
        />
        <line x1={originX + s(6) - drumR * 0.65} y1={shaftY - drumR * 0.65}
          x2={originX + s(6) + drumR * 0.65} y2={shaftY + drumR * 0.65}
          stroke="#000" strokeWidth="0.75" />
        <line x1={originX + s(6) + drumR * 0.65} y1={shaftY - drumR * 0.65}
          x2={originX + s(6) - drumR * 0.65} y2={shaftY + drumR * 0.65}
          stroke="#000" strokeWidth="0.75" />

        {/* Spring coils (zigzag — more visible) */}
        <path
          d={generateSpringPath(originX + s(8), shaftY, originX + s(20), 14)}
          fill="none"
          stroke="#000"
          strokeWidth="1"
        />

        {/* Spring end caps (small circles) */}
        <circle cx={originX + s(8)} cy={shaftY} r={1.5} fill="#000" stroke="#000" strokeWidth="0.5" />
        <circle cx={originX + s(20)} cy={shaftY} r={1.5} fill="#000" stroke="#000" strokeWidth="0.5" />

        {/* Cable from drum to bottom bracket */}
        <line
          x1={originX + s(6)}
          y1={shaftY + drumR}
          x2={originX + s(DOOR_THICKNESS + 1)}
          y2={floorY - s(4)}
          stroke="#000"
          strokeWidth="0.75"
          strokeDasharray="4,2"
        />
        {/* Bottom bracket */}
        <rect
          x={originX + s(DOOR_THICKNESS) - 1}
          y={floorY - s(6)}
          width={4}
          height={s(4)}
          fill="#000"
          stroke="#000"
          strokeWidth="0.5"
        />

        {/* CL SHAFT symbol (centerline) */}
        <line
          x1={originX + s(22) + 4}
          y1={shaftY}
          x2={originX + s(22) + baseUnit * 2}
          y2={shaftY}
          stroke="#000"
          strokeWidth="0.5"
          strokeDasharray="6,2,2,2"
        />
        <text
          x={originX + s(22) + baseUnit * 2.5}
          y={shaftY + fontTiny * 0.35}
          fontSize={fontTiny}
          fill="#333"
          textAnchor="start"
          letterSpacing="0.5"
        >
          CL SHAFT
        </text>
      </g>
    )
  }

  /**
   * Generate a zigzag spring path with more pronounced coils
   */
  function generateSpringPath(startX, centerY, endX, coilCount) {
    const amplitude = baseUnit * 0.5
    const segW = (endX - startX) / coilCount
    let d = `M ${startX} ${centerY}`
    for (let i = 0; i < coilCount; i++) {
      const px = startX + segW * (i + 0.5)
      const py = centerY + (i % 2 === 0 ? amplitude : -amplitude)
      d += ` L ${px} ${py}`
    }
    d += ` L ${endX} ${centerY}`
    return d
  }

  /**
   * Render dimension lines with 45-degree diagonal tick marks (architectural style).
   * Right-side vertical dims are staggered so they never overlap.
   */
  function renderDimensions() {
    const elements = []
    const lift = g.lift

    // Spacing between staggered right-side dimension lines
    const dimStagger = baseUnit * 4.5

    /**
     * Draw a dimension line with 45-degree diagonal tick marks.
     */
    function dimLine(key, x1, y1, x2, y2, label, offset = 0, side = 'right') {
      const isVertical = Math.abs(x1 - x2) < 1
      const isHorizontal = Math.abs(y1 - y2) < 1

      if (isVertical) {
        const x = x1 + offset
        const yMin = Math.min(y1, y2)
        const yMax = Math.max(y1, y2)
        const span = yMax - yMin

        if (span < baseUnit * 1.2) return

        const labelX = x + (side === 'right' ? baseUnit * 1.2 : -baseUnit * 1.2)

        elements.push(
          <g key={key}>
            {/* Dimension line */}
            <line x1={x} y1={yMin} x2={x} y2={yMax} stroke="#000" strokeWidth="0.5" />
            {/* 45-degree diagonal tick marks */}
            <DiagTick x={x} y={yMin} />
            <DiagTick x={x} y={yMax} />
            {/* Extension lines (dashed) */}
            {offset !== 0 && (
              <>
                <line x1={x1} y1={yMin} x2={x - (offset > 0 ? 2 : -2)} y2={yMin}
                  stroke="#000" strokeWidth="0.3" strokeDasharray="2,2" />
                <line x1={x1} y1={yMax} x2={x - (offset > 0 ? 2 : -2)} y2={yMax}
                  stroke="#000" strokeWidth="0.3" strokeDasharray="2,2" />
              </>
            )}
            {/* Label — rotated -90 along the dimension line */}
            <text
              x={labelX}
              y={(yMin + yMax) / 2}
              fontSize={fontSmall}
              fill="#000"
              textAnchor="middle"
              dominantBaseline="middle"
              transform={`rotate(-90, ${labelX}, ${(yMin + yMax) / 2})`}
              letterSpacing="0.5"
            >
              {label}
            </text>
          </g>
        )
      } else if (isHorizontal) {
        const y = y1 + offset
        const xMin = Math.min(x1, x2)
        const xMax = Math.max(x1, x2)

        elements.push(
          <g key={key}>
            <line x1={xMin} y1={y} x2={xMax} y2={y} stroke="#000" strokeWidth="0.5" />
            {/* 45-degree diagonal tick marks */}
            <DiagTick x={xMin} y={y} />
            <DiagTick x={xMax} y={y} />
            {/* Extension lines */}
            {offset !== 0 && (
              <>
                <line x1={xMin} y1={y1} x2={xMin} y2={y - (offset > 0 ? 2 : -2)}
                  stroke="#000" strokeWidth="0.3" strokeDasharray="2,2" />
                <line x1={xMax} y1={y1} x2={xMax} y2={y - (offset > 0 ? 2 : -2)}
                  stroke="#000" strokeWidth="0.3" strokeDasharray="2,2" />
              </>
            )}
            {/* Label */}
            <text
              x={(xMin + xMax) / 2}
              y={y + (offset > 0 ? baseUnit * 1.5 : -baseUnit * 0.6)}
              fontSize={fontSmall}
              fill="#000"
              textAnchor="middle"
              letterSpacing="0.5"
            >
              {label}
            </text>
          </g>
        )
      }
    }

    // --- Right-side vertical dimensions, staggered ---
    const dimBaseX = originX + s(g.backroom) + 25

    let stIdx = 0

    // 1. Door Height
    dimLine('dim-doorH', dimBaseX, originY, dimBaseX, floorY,
      `DOOR HEIGHT: ${formatDim(g.doorH)}`, 20 + stIdx * dimStagger)
    stIdx++

    // 2. Req. Headroom (all black now)
    dimLine('dim-headroom', dimBaseX, originY - s(g.headroomMin), dimBaseX, originY,
      `REQ. HEADROOM: ${formatDim(g.headroomMin)}`, 20 + stIdx * dimStagger)
    stIdx++

    // 3. UST dimension (if applicable)
    if (lift !== 'lhr_front' && lift !== 'lhr_rear') {
      dimLine('dim-ust', dimBaseX, originY - s(g.ust), dimBaseX, originY,
        `U.S.T.: ${formatDim(g.ust)}`, 20 + stIdx * dimStagger)
      stIdx++
    }

    // 4. CL Shaft dimension (if applicable)
    if (lift !== 'lhr_front' && lift !== 'lhr_rear') {
      dimLine('dim-clshaft', dimBaseX, originY - s(g.clShaft), dimBaseX, originY,
        `CL SHAFT: ${formatDim(g.clShaft)}`, 20 + stIdx * dimStagger)
      stIdx++
    }

    // High lift extra dimension
    if (lift === 'high_lift' && g.hl > 0) {
      dimLine('dim-hl', originX + s(DOOR_THICKNESS + g.tSize + 6), originY,
        originX + s(DOOR_THICKNESS + g.tSize + 6), originY - s(g.hl),
        `HIGH LIFT: ${formatDim(g.hl)}`, 0)
    }

    // Backroom dimension (horizontal, above ceiling)
    dimLine('dim-backroom', originX, originY - s(g.headroomMin), originX + s(g.backroom), originY - s(g.headroomMin),
      `MIN. REQ. BACKROOM: ${formatDim(g.backroom)}`, -(baseUnit * 3.5))

    return <g className="dimensions">{elements}</g>
  }

  /**
   * Render panel cross-section callout (bottom-right area)
   */
  function renderPanelCallout() {
    const boxW = baseUnit * 13
    const boxH = baseUnit * 8
    const boxX = svgW - MARGIN_RIGHT - boxW - baseUnit
    const boxY = svgH - MARGIN_BOTTOM + baseUnit

    return (
      <g className="panel-callout">
        <rect x={boxX} y={boxY} width={boxW} height={boxH}
          fill="#fff" stroke="#000" strokeWidth="1" />
        {/* Header bar */}
        <line x1={boxX} y1={boxY + baseUnit * 1.4} x2={boxX + boxW} y2={boxY + baseUnit * 1.4}
          stroke="#000" strokeWidth="0.5" />
        <text x={boxX + boxW / 2} y={boxY + baseUnit * 1.1} fontSize={fontSmall} fontWeight="bold"
          textAnchor="middle" fill="#000" letterSpacing="1">
          PANEL SECTION
        </text>

        {/* Panel cross-section illustration */}
        {/* Exterior steel skin */}
        <rect x={boxX + baseUnit * 1.5} y={boxY + baseUnit * 2.2} width={boxW - baseUnit * 3} height={baseUnit * 0.4}
          fill="#bbb" stroke="#000" strokeWidth="0.5" />
        {/* Insulation core */}
        <rect x={boxX + baseUnit * 1.5} y={boxY + baseUnit * 2.6} width={boxW - baseUnit * 3} height={baseUnit * 2}
          fill="url(#insulFill)" stroke="#000" strokeWidth="0.5" />
        {/* Interior steel skin */}
        <rect x={boxX + baseUnit * 1.5} y={boxY + baseUnit * 4.6} width={boxW - baseUnit * 3} height={baseUnit * 0.4}
          fill="#bbb" stroke="#000" strokeWidth="0.5" />

        {/* Labels with leader lines */}
        <text x={boxX + boxW - baseUnit * 0.8} y={boxY + baseUnit * 2.5} fontSize={fontTiny} fill="#333" textAnchor="end">EXT. STEEL</text>
        <text x={boxX + boxW - baseUnit * 0.8} y={boxY + baseUnit * 3.8} fontSize={fontTiny} fill="#333" textAnchor="end">INSULATION</text>
        <text x={boxX + boxW - baseUnit * 0.8} y={boxY + baseUnit * 5.1} fontSize={fontTiny} fill="#333" textAnchor="end">INT. STEEL</text>

        {/* Exterior / Interior markers */}
        <text x={boxX + baseUnit * 1.5} y={boxY + baseUnit * 6.5} fontSize={fontTiny} fill="#333" textAnchor="start">EXT.</text>
        <line x1={boxX + baseUnit * 1.5} y1={boxY + baseUnit * 6.6} x2={boxX + boxW - baseUnit * 1.5} y2={boxY + baseUnit * 6.6}
          stroke="#000" strokeWidth="0.3" />
        <text x={boxX + boxW - baseUnit * 1.5} y={boxY + baseUnit * 6.5} fontSize={fontTiny} fill="#333" textAnchor="end">INT.</text>

        {doorSeries && (
          <text x={boxX + boxW / 2} y={boxY + baseUnit * 7.5} fontSize={fontTiny} textAnchor="middle" fill="#333" fontWeight="bold">
            {doorSeries}
          </text>
        )}
      </g>
    )
  }

  /**
   * Render requirements summary box (bottom-left)
   */
  function renderRequirementsBox() {
    const lineH = baseUnit * 1.6
    const boxW = baseUnit * 24
    const showUstCl = g.lift !== 'lhr_front' && g.lift !== 'lhr_rear'
    const rowCount = showUstCl ? 6.5 : 4.5
    const boxH = lineH * rowCount
    const boxX = baseUnit * 1.5
    const boxY = svgH - MARGIN_BOTTOM + baseUnit

    return (
      <g className="requirements-box">
        <rect x={boxX} y={boxY} width={boxW} height={boxH}
          fill="#fff" stroke="#000" strokeWidth="1" />
        {/* Header */}
        <line x1={boxX} y1={boxY + lineH} x2={boxX + boxW} y2={boxY + lineH}
          stroke="#000" strokeWidth="0.5" />
        <text x={boxX + boxW / 2} y={boxY + lineH * 0.75} fontSize={fontLabel} fontWeight="bold"
          textAnchor="middle" fill="#000" letterSpacing="1">
          CLEARANCE REQUIREMENTS
        </text>

        {/* Row: Req. Headroom */}
        <text x={boxX + baseUnit} y={boxY + lineH * 1.8} fontSize={fontLabel} fill="#000">
          Req. Headroom:
        </text>
        <text x={boxX + boxW - baseUnit} y={boxY + lineH * 1.8} fontSize={fontLabel} fill="#000" textAnchor="end" fontWeight="bold">
          {formatDim(g.headroomMin)}
        </text>

        {/* Row: Min. Backroom */}
        <text x={boxX + baseUnit} y={boxY + lineH * 2.6} fontSize={fontLabel} fill="#000">
          Min. Req. Backroom:
        </text>
        <text x={boxX + boxW - baseUnit} y={boxY + lineH * 2.6} fontSize={fontLabel} fill="#000" textAnchor="end" fontWeight="bold">
          {formatDim(g.backroom)}
        </text>

        {/* Row: Min. Sideroom */}
        <text x={boxX + baseUnit} y={boxY + lineH * 3.4} fontSize={fontLabel} fill="#000">
          Min. Sideroom (ea.):
        </text>
        <text x={boxX + boxW - baseUnit} y={boxY + lineH * 3.4} fontSize={fontLabel} fill="#000" textAnchor="end" fontWeight="bold">
          {formatDim(g.sideroom)}
        </text>

        {showUstCl && (
          <>
            {/* Row: U.S.T. */}
            <text x={boxX + baseUnit} y={boxY + lineH * 4.2} fontSize={fontLabel} fill="#000">
              U.S.T.:
            </text>
            <text x={boxX + boxW - baseUnit} y={boxY + lineH * 4.2} fontSize={fontLabel} fill="#000" textAnchor="end" fontWeight="bold">
              {formatDim(g.ust)}
            </text>
            {/* Row: CL Shaft */}
            <text x={boxX + baseUnit} y={boxY + lineH * 5.0} fontSize={fontLabel} fill="#000">
              CL Shaft:
            </text>
            <text x={boxX + boxW - baseUnit} y={boxY + lineH * 5.0} fontSize={fontLabel} fill="#000" textAnchor="end" fontWeight="bold">
              {formatDim(g.clShaft)}
            </text>
          </>
        )}

        {/* Footer */}
        <text x={boxX + boxW / 2} y={boxY + lineH * (showUstCl ? 6.2 : 4.2)} fontSize={fontTiny} textAnchor="middle" fill="#666" letterSpacing="0.5">
          {g.liftLabel} LIFT | {g.radiusLabel}
        </text>
      </g>
    )
  }

  /**
   * Render title block in bottom-right corner
   */
  function renderTitleBlock() {
    const blockW = baseUnit * 16
    const blockH = baseUnit * 5
    const blockX = svgW - baseUnit * 2 - blockW
    const blockY = svgH - baseUnit * 1.5 - blockH

    // Only show if below panel callout
    const panelCalloutBottom = svgH - MARGIN_BOTTOM + baseUnit + baseUnit * 8
    if (blockY < panelCalloutBottom + baseUnit) return null

    return (
      <g className="title-block">
        <rect x={blockX} y={blockY} width={blockW} height={blockH}
          fill="#fff" stroke="#000" strokeWidth="1" />
        <line x1={blockX} y1={blockY + baseUnit * 1.8} x2={blockX + blockW} y2={blockY + baseUnit * 1.8}
          stroke="#000" strokeWidth="0.5" />
        <line x1={blockX} y1={blockY + baseUnit * 3.2} x2={blockX + blockW} y2={blockY + baseUnit * 3.2}
          stroke="#000" strokeWidth="0.5" />
        <text x={blockX + blockW / 2} y={blockY + baseUnit * 1.3} fontSize={fontSmall} fontWeight="bold"
          textAnchor="middle" fill="#000" letterSpacing="1">
          {doorSeries || 'THERMALEX'}
        </text>
        <text x={blockX + blockW / 2} y={blockY + baseUnit * 2.7} fontSize={fontTiny}
          textAnchor="middle" fill="#333">
          {doorType.toUpperCase()} DOOR
        </text>
        <text x={blockX + blockW / 2} y={blockY + baseUnit * 4.2} fontSize={fontTiny}
          textAnchor="middle" fill="#333">
          OPEN DC DISTRIBUTION
        </text>
      </g>
    )
  }
}

export default SideElevationDrawing
