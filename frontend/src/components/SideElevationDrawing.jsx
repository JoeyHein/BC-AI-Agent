/**
 * SideElevationDrawing Component
 * Renders a professional architectural side elevation view of a garage door installation.
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
  // Scales all fonts, ticks, margins, and spacing with the drawing size.
  const baseUnit = Math.max(5, Math.min(12, Math.sqrt(g.doorH * scale) * 0.8))

  // Font sizes
  const fontTitle = baseUnit * 1.6
  const fontSubtitle = baseUnit * 1.2
  const fontLabel = baseUnit
  const fontSmall = baseUnit * 0.8

  // Dimension helpers
  const tickLen = baseUnit * 0.5
  const extGap = baseUnit * 0.3

  // Margins scale with content
  const MARGIN_LEFT = Math.max(80, baseUnit * 10)
  const MARGIN_RIGHT = Math.max(80, baseUnit * 10)
  const MARGIN_TOP = Math.max(60, baseUnit * 8)
  const MARGIN_BOTTOM = Math.max(100, baseUnit * 12)

  const WALL_THICKNESS = 8 // inches
  const WALL_DRAW_W = 14 // pixels for wall hatching width
  const DOOR_THICKNESS = 4 // inches

  // Scaling helper: inches to pixels
  const s = (inches) => inches * scale

  // Compute drawing extents
  const layout = useMemo(() => {
    const aboveDoor = Math.max(g.headroomMin, g.clShaft + 6)
    const totalVertical = g.doorH + aboveDoor
    const totalHorizontal = WALL_THICKNESS + g.backroom + 12

    const contentW = s(totalHorizontal)
    const contentH = s(totalVertical)

    const rawW = MARGIN_LEFT + contentW + MARGIN_RIGHT
    const rawH = MARGIN_TOP + contentH + MARGIN_BOTTOM

    // Enforce minimum SVG width of 500
    const svgW = Math.max(500, rawW)
    const svgH = rawH

    const originX = MARGIN_LEFT + WALL_DRAW_W
    const originY = MARGIN_TOP + s(aboveDoor)

    return { svgW, svgH, originX, originY, aboveDoor, contentW, contentH }
  }, [g, scale, MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM])

  const { svgW, svgH, originX, originY } = layout

  // Floor Y = origin + door height
  const floorY = originY + s(g.doorH)

  // Curve center and geometry for quarter-circle track
  const curveStartY = originY - (g.lift === 'high_lift' ? s(g.hl) : 0)
  const horizontalTrackEndX = originX + s(g.backroom)

  // Shaft Y position
  const shaftY = originY - s(g.clShaft)
  // UST Y
  const ustY = originY - s(g.ust)

  return (
    <div className="side-elevation-drawing bg-white border border-gray-300 rounded-lg overflow-hidden">
      <svg
        viewBox={`0 0 ${svgW} ${svgH}`}
        style={{ fontFamily: "'Courier New', monospace", maxWidth: `${svgW}px`, width: '100%' }}
      >
        <defs>
          {/* Concrete/masonry hatching */}
          <pattern id="sideHatch" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="#888" strokeWidth="0.5" />
          </pattern>
          <pattern id="sideHatch2" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(-45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="#888" strokeWidth="0.4" />
          </pattern>
          {/* Insulation pattern for panel callout */}
          <pattern id="insulFill" patternUnits="userSpaceOnUse" width="12" height="8">
            <path d="M0,4 Q3,0 6,4 Q9,8 12,4" fill="none" stroke="#aaa" strokeWidth="0.5" />
          </pattern>
        </defs>

        {/* ===== TITLE BLOCK ===== */}
        <text x={svgW / 2} y={fontTitle + 4} fontSize={fontTitle} fontWeight="bold" textAnchor="middle" fill="#000">
          {title}
        </text>
        <text x={svgW / 2} y={fontTitle + 4 + fontSubtitle + 4} fontSize={fontSubtitle} textAnchor="middle" fill="#333">
          {g.trackTypeLabel}
        </text>
        {doorSeries && (
          <text x={svgW / 2} y={fontTitle + 4 + fontSubtitle + 4 + fontLabel + 4} fontSize={fontSmall} textAnchor="middle" fill="#555">
            {doorSeries} | {doorType.toUpperCase()}
          </text>
        )}

        {/* ===== FLOOR LINE ===== */}
        <line
          x1={originX - WALL_DRAW_W - 20}
          y1={floorY}
          x2={originX + s(g.backroom) + 30}
          y2={floorY}
          stroke="#000"
          strokeWidth="2.5"
        />
        {/* Ground hatching below floor */}
        {Array.from({ length: Math.ceil((s(g.backroom) + WALL_DRAW_W + 50) / 8) }, (_, i) => (
          <line
            key={`gh${i}`}
            x1={originX - WALL_DRAW_W - 20 + i * 8}
            y1={floorY + 2}
            x2={originX - WALL_DRAW_W - 20 + i * 8 - 6}
            y2={floorY + 8}
            stroke="#666"
            strokeWidth="0.5"
          />
        ))}

        {/* ===== WALL / HEADER SECTION (hatched) ===== */}
        <rect
          x={originX - WALL_DRAW_W}
          y={originY - s(g.headroomMin + 20)}
          width={WALL_DRAW_W}
          height={s(g.headroomMin + 20) + s(g.doorH) + 16}
          fill="url(#sideHatch)"
          stroke="#000"
          strokeWidth="1"
        />
        <rect
          x={originX - WALL_DRAW_W}
          y={originY - s(g.headroomMin + 20)}
          width={WALL_DRAW_W}
          height={s(g.headroomMin + 20) + s(g.doorH) + 16}
          fill="url(#sideHatch2)"
          stroke="none"
        />
        <rect
          x={originX - WALL_DRAW_W}
          y={originY - s(g.headroomMin + 20)}
          width={WALL_DRAW_W}
          height={s(g.headroomMin + 20) + s(g.doorH) + 16}
          fill="none"
          stroke="#000"
          strokeWidth="1"
        />

        {/* ===== EXTERIOR / INTERIOR LABELS ===== */}
        <text
          x={originX - WALL_DRAW_W - baseUnit}
          y={originY + s(g.doorH / 2)}
          fontSize={fontLabel}
          fill="#000"
          textAnchor="middle"
          transform={`rotate(-90, ${originX - WALL_DRAW_W - baseUnit}, ${originY + s(g.doorH / 2)})`}
          fontWeight="bold"
        >
          EXTERIOR
        </text>
        <text
          x={originX + s(g.backroom / 2)}
          y={floorY + baseUnit * 2.5}
          fontSize={fontLabel}
          fill="#000"
          textAnchor="middle"
          fontWeight="bold"
        >
          INTERIOR
        </text>

        {/* ===== CEILING LINE (dashed) ===== */}
        <line
          x1={originX}
          y1={originY - s(g.headroomMin)}
          x2={originX + s(g.backroom) + 20}
          y2={originY - s(g.headroomMin)}
          stroke="#000"
          strokeWidth="0.75"
          strokeDasharray="8,4"
        />
        <text
          x={originX + s(g.backroom) + 22}
          y={originY - s(g.headroomMin) + fontSmall * 0.4}
          fontSize={fontSmall}
          fill="#555"
        >
          CEILING
        </text>

        {/* ===== DOOR IN CLOSED POSITION (solid) ===== */}
        <rect
          x={originX}
          y={originY}
          width={s(DOOR_THICKNESS)}
          height={s(g.doorH)}
          fill="#ddd"
          stroke="#000"
          strokeWidth="1"
        />
        {/* Panel lines on closed door */}
        {g.doorH > 20 && Array.from({ length: Math.floor(g.doorH / (g.doorH / (Math.round(g.doorH / 21) || 4))) }, (_, i) => {
          const panelCount = Math.round(g.doorH / 21) || 4
          const panelH = g.doorH / panelCount
          const py = originY + s(panelH * (i + 1))
          if (i >= panelCount - 1) return null
          return (
            <line
              key={`panel${i}`}
              x1={originX}
              y1={py}
              x2={originX + s(DOOR_THICKNESS)}
              y2={py}
              stroke="#999"
              strokeWidth="0.5"
            />
          )
        })}
        <text
          x={originX + s(DOOR_THICKNESS / 2)}
          y={originY + s(g.doorH / 2)}
          fontSize={fontSmall}
          fill="#333"
          textAnchor="middle"
          transform={`rotate(-90, ${originX + s(DOOR_THICKNESS / 2)}, ${originY + s(g.doorH / 2)})`}
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
      elements.push(
        <g key="vert-tracks">
          <line
            x1={originX + s(DOOR_THICKNESS + 1)}
            y1={floorY}
            x2={originX + s(DOOR_THICKNESS + 1)}
            y2={originY - s(g.verticalTrackLen - g.doorH)}
            stroke="#000"
            strokeWidth="1.5"
          />
          <line
            x1={originX + s(DOOR_THICKNESS + 1 + g.tSize)}
            y1={floorY}
            x2={originX + s(DOOR_THICKNESS + 1 + g.tSize)}
            y2={originY - s(g.verticalTrackLen - g.doorH)}
            stroke="#000"
            strokeWidth="1.5"
          />
          <text
            x={originX + s(DOOR_THICKNESS + 1 + g.tSize / 2)}
            y={originY - s((g.verticalTrackLen - g.doorH) / 2)}
            fontSize={fontSmall}
            fill="#555"
            textAnchor="middle"
            transform={`rotate(-90, ${originX + s(DOOR_THICKNESS + 1 + g.tSize / 2)}, ${originY - s((g.verticalTrackLen - g.doorH) / 2)})`}
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
          {/* LHR label */}
          <text
            x={originX + s(g.backroom / 2)}
            y={originY - s(g.headroomMin) - baseUnit}
            fontSize={fontSmall}
            fill="#555"
            textAnchor="middle"
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
                fontSize={fontSmall}
                fill="#000"
                textAnchor="start"
                transform={`rotate(-90, ${originX + s(DOOR_THICKNESS + 1 + g.tSize + 3)}, ${originY - s(g.hl / 2)})`}
              >
                HIGH LIFT {formatDim(g.hl)}
              </text>
            </g>
          )}

          {/* Quarter-circle curve */}
          {g.curveType !== 'none' && (
            <g key="curve">
              <path
                d={`M ${originX + s(DOOR_THICKNESS + 1)} ${vtTop}
                    A ${s(g.radius)} ${s(g.radius)} 0 0 0
                    ${originX + s(DOOR_THICKNESS + 1 + g.radius)} ${vtTop - s(g.radius)}`}
                fill="none"
                stroke="#000"
                strokeWidth="1"
              />
              <path
                d={`M ${originX + s(DOOR_THICKNESS + 1 + g.tSize)} ${vtTop}
                    A ${s(g.radius - g.tSize)} ${s(g.radius - g.tSize)} 0 0 0
                    ${originX + s(DOOR_THICKNESS + 1 + g.radius)} ${vtTop - s(g.radius - g.tSize)}`}
                fill="none"
                stroke="#000"
                strokeWidth="1"
              />
              <text
                x={originX + s(DOOR_THICKNESS + 1 + g.radius * 0.35)}
                y={vtTop - s(g.radius * 0.35) - baseUnit * 0.5}
                fontSize={fontSmall}
                fill="#555"
              >
                {g.radiusLabel}
              </text>
            </g>
          )}

          {/* Horizontal track */}
          {g.horizontalTrackLen > 0 && (
            <g key="horiz-track">
              <line
                x1={originX + s(DOOR_THICKNESS + 1 + g.radius)}
                y1={vtTop - s(g.radius)}
                x2={horizontalTrackEndX}
                y2={vtTop - s(g.radius)}
                stroke="#000"
                strokeWidth="1"
              />
              <line
                x1={originX + s(DOOR_THICKNESS + 1 + g.radius)}
                y1={vtTop - s(g.radius - g.tSize)}
                x2={horizontalTrackEndX}
                y2={vtTop - s(g.radius - g.tSize)}
                stroke="#000"
                strokeWidth="1"
              />
              <line
                x1={horizontalTrackEndX}
                y1={vtTop - s(g.radius) - 4}
                x2={horizontalTrackEndX}
                y2={vtTop - s(g.radius - g.tSize) + 4}
                stroke="#000"
                strokeWidth="1.5"
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
            fontSize={fontSmall}
            fill="#555"
            textAnchor="middle"
            transform={`rotate(-90, ${originX + s(DOOR_THICKNESS / 2)}, ${originY - s(g.doorH / 2)})`}
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
            fontSize={fontSmall}
            fill="#555"
            textAnchor="middle"
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
        <text
          x={originX + s(DOOR_THICKNESS + 1 + g.radius + g.doorH / 2)}
          y={trackCenterY - s(DOOR_THICKNESS / 2) - baseUnit * 0.4}
          fontSize={fontSmall}
          fill="#555"
          textAnchor="middle"
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
          <line x1={originX + s(2)} y1={sy} x2={originX + s(18)} y2={sy}
            stroke="#000" strokeWidth="2" />
          <circle cx={originX + s(6)} cy={sy} r={drumR}
            fill="none" stroke="#000" strokeWidth="1" />
          <line x1={originX + s(8)} y1={sy - 2} x2={originX + s(16)} y2={sy - 2}
            stroke="#000" strokeWidth="1.5" />
          <line x1={originX + s(8)} y1={sy + 2} x2={originX + s(16)} y2={sy + 2}
            stroke="#000" strokeWidth="1.5" />
          <line x1={originX + s(6)} y1={sy + drumR}
            x2={originX + s(4)} y2={floorY - s(4)}
            stroke="#000" strokeWidth="0.75" strokeDasharray="4,2" />
          <text x={originX + s(10)} y={sy - baseUnit * 0.8} fontSize={fontSmall} fill="#555" textAnchor="middle">
            SHAFT &amp; SPRING
          </text>
        </g>
      )
    }

    return (
      <g className="shaft-assembly">
        <line
          x1={originX + s(2)}
          y1={shaftY}
          x2={originX + s(20)}
          y2={shaftY}
          stroke="#000"
          strokeWidth="2"
        />
        <circle
          cx={originX + s(6)}
          cy={shaftY}
          r={drumR}
          fill="none"
          stroke="#000"
          strokeWidth="1"
        />
        {/* X inside drum */}
        <line x1={originX + s(6) - drumR * 0.6} y1={shaftY - drumR * 0.6}
          x2={originX + s(6) + drumR * 0.6} y2={shaftY + drumR * 0.6}
          stroke="#000" strokeWidth="0.5" />
        <line x1={originX + s(6) + drumR * 0.6} y1={shaftY - drumR * 0.6}
          x2={originX + s(6) - drumR * 0.6} y2={shaftY + drumR * 0.6}
          stroke="#000" strokeWidth="0.5" />
        {/* Spring coils (zigzag) */}
        <path
          d={`M ${originX + s(8)} ${shaftY - 2} ${Array.from({ length: 8 }, (_, i) => {
            const px = originX + s(8) + (s(10) / 8) * (i + 1)
            const py = shaftY + (i % 2 === 0 ? 2 : -2)
            return `L ${px} ${py}`
          }).join(' ')}`}
          fill="none"
          stroke="#000"
          strokeWidth="1"
        />
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
        {/* Labels */}
        <text
          x={originX + s(12)}
          y={shaftY - baseUnit * 0.8}
          fontSize={fontSmall}
          fill="#555"
          textAnchor="middle"
        >
          TORSION SPRING &amp; SHAFT
        </text>
        <text
          x={originX + s(6)}
          y={shaftY + drumR + baseUnit * 1.2}
          fontSize={fontSmall}
          fill="#555"
          textAnchor="middle"
        >
          DRUM
        </text>
      </g>
    )
  }

  /**
   * Render dimension lines with tick marks — all sizes proportional.
   * Right-side vertical dims are staggered so they never overlap.
   */
  function renderDimensions() {
    const elements = []
    const lift = g.lift

    // Spacing between staggered right-side dimension lines
    const dimStagger = baseUnit * 3

    /**
     * Draw a dimension line between two points with tick marks and a label.
     * offset: pixel offset from the anchor x/y (for staggering).
     */
    function dimLine(key, x1, y1, x2, y2, label, color = '#000', offset = 0, side = 'right') {
      const isVertical = Math.abs(x1 - x2) < 1
      const isHorizontal = Math.abs(y1 - y2) < 1

      if (isVertical) {
        const x = x1 + offset
        const yMin = Math.min(y1, y2)
        const yMax = Math.max(y1, y2)
        const span = yMax - yMin

        // Skip if the span is too small to read
        if (span < baseUnit * 1.2) return

        const labelX = x + (side === 'right' ? baseUnit * 1 : -baseUnit * 1)

        elements.push(
          <g key={key}>
            {/* Dimension line */}
            <line x1={x} y1={yMin} x2={x} y2={yMax} stroke={color} strokeWidth="0.5" />
            {/* Top tick */}
            <line x1={x - tickLen} y1={yMin} x2={x + tickLen} y2={yMin} stroke={color} strokeWidth="0.75" />
            {/* Bottom tick */}
            <line x1={x - tickLen} y1={yMax} x2={x + tickLen} y2={yMax} stroke={color} strokeWidth="0.75" />
            {/* Extension lines */}
            {offset !== 0 && (
              <>
                <line x1={x1} y1={yMin} x2={x + (offset > 0 ? -extGap : extGap)} y2={yMin}
                  stroke={color} strokeWidth="0.3" strokeDasharray="2,2" />
                <line x1={x1} y1={yMax} x2={x + (offset > 0 ? -extGap : extGap)} y2={yMax}
                  stroke={color} strokeWidth="0.3" strokeDasharray="2,2" />
              </>
            )}
            {/* Label — rotated -90 along the dimension line */}
            <text
              x={labelX}
              y={(yMin + yMax) / 2}
              fontSize={fontSmall}
              fill={color}
              textAnchor="middle"
              dominantBaseline="middle"
              transform={`rotate(-90, ${labelX}, ${(yMin + yMax) / 2})`}
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
            <line x1={xMin} y1={y} x2={xMax} y2={y} stroke={color} strokeWidth="0.5" />
            {/* Left tick */}
            <line x1={xMin} y1={y - tickLen} x2={xMin} y2={y + tickLen} stroke={color} strokeWidth="0.75" />
            {/* Right tick */}
            <line x1={xMax} y1={y - tickLen} x2={xMax} y2={y + tickLen} stroke={color} strokeWidth="0.75" />
            {/* Extension lines */}
            {offset !== 0 && (
              <>
                <line x1={xMin} y1={y1} x2={xMin} y2={y + (offset > 0 ? -extGap : extGap)}
                  stroke={color} strokeWidth="0.3" strokeDasharray="2,2" />
                <line x1={xMax} y1={y1} x2={xMax} y2={y + (offset > 0 ? -extGap : extGap)}
                  stroke={color} strokeWidth="0.3" strokeDasharray="2,2" />
              </>
            )}
            {/* Label */}
            <text
              x={(xMin + xMax) / 2}
              y={y + (offset > 0 ? baseUnit * 1.5 : -baseUnit * 0.6)}
              fontSize={fontSmall}
              fill={color}
              textAnchor="middle"
            >
              {label}
            </text>
          </g>
        )
      }
    }

    // --- Right-side vertical dimensions, staggered ---
    // Base X for right-side dims
    const dimBaseX = originX + s(g.backroom) + 20

    // Stagger index counter
    let stIdx = 0

    // 1. Door Height (always shown)
    dimLine('dim-doorH', dimBaseX, originY, dimBaseX, floorY,
      `DOOR HEIGHT: ${formatDim(g.doorH)}`, '#000', 20 + stIdx * dimStagger)
    stIdx++

    // 2. Headroom
    dimLine('dim-headroom', dimBaseX, originY - s(g.headroomMin), dimBaseX, originY,
      `MIN. HEADROOM: ${formatDim(g.headroomMin)}`, '#C00', 20 + stIdx * dimStagger)
    stIdx++

    // 3. UST (skip for LHR)
    if (lift !== 'lhr_front' && lift !== 'lhr_rear') {
      dimLine('dim-ust', dimBaseX, originY - s(g.ust), dimBaseX, originY,
        `U.S.T.: ${formatDim(g.ust)}`, '#555', 20 + stIdx * dimStagger)
      stIdx++
    }

    // 4. CL Shaft (skip for LHR)
    if (lift !== 'lhr_front' && lift !== 'lhr_rear') {
      const clOffset = 20 + stIdx * dimStagger
      const clX = dimBaseX + clOffset
      elements.push(
        <g key="cl-shaft">
          {/* Dashed reference line at shaft height */}
          <line
            x1={originX - 4}
            y1={shaftY}
            x2={originX + s(20) + 5}
            y2={shaftY}
            stroke="#555"
            strokeWidth="0.3"
            strokeDasharray="4,3"
          />
          {/* Dimension line */}
          <line x1={clX} y1={originY} x2={clX} y2={shaftY} stroke="#555" strokeWidth="0.5" />
          {/* Ticks */}
          <line x1={clX - tickLen} y1={originY} x2={clX + tickLen} y2={originY} stroke="#555" strokeWidth="0.5" />
          <line x1={clX - tickLen} y1={shaftY} x2={clX + tickLen} y2={shaftY} stroke="#555" strokeWidth="0.5" />
          {/* Extension lines */}
          <line x1={dimBaseX} y1={originY} x2={clX - extGap} y2={originY}
            stroke="#555" strokeWidth="0.3" strokeDasharray="2,2" />
          <line x1={dimBaseX} y1={shaftY} x2={clX - extGap} y2={shaftY}
            stroke="#555" strokeWidth="0.3" strokeDasharray="2,2" />
          {/* Label */}
          <text
            x={clX + baseUnit * 1}
            y={originY - s(g.clShaft / 2)}
            fontSize={fontSmall}
            fill="#555"
            textAnchor="middle"
            transform={`rotate(-90, ${clX + baseUnit * 1}, ${originY - s(g.clShaft / 2)})`}
          >
            CL SHAFT: {formatDim(g.clShaft)}
          </text>
        </g>
      )
      stIdx++
    }

    // High lift extra dimension (inline, not staggered on the right)
    if (lift === 'high_lift' && g.hl > 0) {
      dimLine('dim-hl', originX + s(DOOR_THICKNESS + g.tSize + 6), originY,
        originX + s(DOOR_THICKNESS + g.tSize + 6), originY - s(g.hl),
        `HIGH LIFT: ${formatDim(g.hl)}`, '#00C', 0)
    }

    // Backroom dimension (horizontal, above ceiling)
    dimLine('dim-backroom', originX, originY - s(g.headroomMin), originX + s(g.backroom), originY - s(g.headroomMin),
      `MIN. BACKROOM: ${formatDim(g.backroom)}`, '#000', -(baseUnit * 2))

    return <g className="dimensions">{elements}</g>
  }

  /**
   * Render panel cross-section callout (top-right)
   */
  function renderPanelCallout() {
    const boxW = baseUnit * 12
    const boxH = baseUnit * 7
    const boxX = svgW - MARGIN_RIGHT - boxW - baseUnit
    const boxY = MARGIN_TOP

    return (
      <g className="panel-callout">
        <rect x={boxX} y={boxY} width={boxW} height={boxH}
          fill="#fff" stroke="#000" strokeWidth="0.75" />
        <text x={boxX + boxW / 2} y={boxY + baseUnit * 1.2} fontSize={fontSmall} fontWeight="bold"
          textAnchor="middle" fill="#000">
          PANEL SECTION
        </text>
        {/* Outer steel skin */}
        <rect x={boxX + baseUnit} y={boxY + baseUnit * 2} width={boxW - baseUnit * 2} height={baseUnit * 0.4}
          fill="#bbb" stroke="#000" strokeWidth="0.5" />
        {/* Insulation core */}
        <rect x={boxX + baseUnit} y={boxY + baseUnit * 2.4} width={boxW - baseUnit * 2} height={baseUnit * 1.8}
          fill="url(#insulFill)" stroke="#000" strokeWidth="0.5" />
        {/* Inner steel skin */}
        <rect x={boxX + baseUnit} y={boxY + baseUnit * 4.2} width={boxW - baseUnit * 2} height={baseUnit * 0.4}
          fill="#bbb" stroke="#000" strokeWidth="0.5" />
        {/* Labels */}
        <text x={boxX + boxW - baseUnit * 0.5} y={boxY + baseUnit * 2.4} fontSize={fontSmall * 0.7} fill="#555" textAnchor="end">STEEL</text>
        <text x={boxX + boxW - baseUnit * 0.5} y={boxY + baseUnit * 3.5} fontSize={fontSmall * 0.7} fill="#555" textAnchor="end">INSUL.</text>
        <text x={boxX + boxW - baseUnit * 0.5} y={boxY + baseUnit * 4.6} fontSize={fontSmall * 0.7} fill="#555" textAnchor="end">STEEL</text>
        {doorSeries && (
          <text x={boxX + boxW / 2} y={boxY + baseUnit * 6.2} fontSize={fontSmall * 0.8} textAnchor="middle" fill="#333">
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
    const boxH = lineH * 4.5
    const boxX = baseUnit * 1.5
    const boxY = svgH - MARGIN_BOTTOM + baseUnit

    return (
      <g className="requirements-box">
        <rect x={boxX} y={boxY} width={boxW} height={boxH}
          fill="#f9f9f9" stroke="#000" strokeWidth="0.75" />
        <line x1={boxX} y1={boxY + lineH} x2={boxX + boxW} y2={boxY + lineH}
          stroke="#000" strokeWidth="0.5" />
        <text x={boxX + boxW / 2} y={boxY + lineH * 0.75} fontSize={fontLabel} fontWeight="bold"
          textAnchor="middle" fill="#000">
          CLEARANCE REQUIREMENTS
        </text>
        <text x={boxX + baseUnit} y={boxY + lineH * 1.8} fontSize={fontLabel} fill="#000">
          Min. Headroom:
        </text>
        <text x={boxX + boxW - baseUnit} y={boxY + lineH * 1.8} fontSize={fontLabel} fill="#000" textAnchor="end" fontWeight="bold">
          {formatDim(g.headroomMin)}
        </text>
        <text x={boxX + baseUnit} y={boxY + lineH * 2.6} fontSize={fontLabel} fill="#000">
          Min. Backroom:
        </text>
        <text x={boxX + boxW - baseUnit} y={boxY + lineH * 2.6} fontSize={fontLabel} fill="#000" textAnchor="end" fontWeight="bold">
          {formatDim(g.backroom)}
        </text>
        <text x={boxX + baseUnit} y={boxY + lineH * 3.4} fontSize={fontLabel} fill="#000">
          Min. Sideroom (ea.):
        </text>
        <text x={boxX + boxW - baseUnit} y={boxY + lineH * 3.4} fontSize={fontLabel} fill="#000" textAnchor="end" fontWeight="bold">
          {formatDim(g.sideroom)}
        </text>
        <text x={boxX + boxW / 2} y={boxY + lineH * 4.2} fontSize={fontSmall} textAnchor="middle" fill="#888">
          {g.liftLabel} LIFT | {g.radiusLabel}
        </text>
      </g>
    )
  }
}

export default SideElevationDrawing
