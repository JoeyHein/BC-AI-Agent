/**
 * SideElevationDrawing Component
 * Renders a professional architectural side elevation view of a garage door installation.
 * Supports standard, high_lift, vertical, lhr_front, lhr_rear lift types.
 * Uses exact Thermalex geometry from the backend when available.
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
  // If fractional remainder, show decimal inches
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
    // Use geometry from backend when available, otherwise calculate fallback
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
      // Fallback calculations
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
      doorH,
      doorW,
      radius,
      tSize,
      hl,
      lift,
      headroomMin,
      backroom,
      sideroom,
      ust,
      clShaft,
      verticalTrackLen,
      horizontalTrackLen,
      curveType,
      trackTypeLabel,
      radiusLabel,
      liftLabel,
    }
  }, [width, height, trackRadius, trackSize, liftType, highLiftInches, geometry])

  // Drawing layout constants
  const MARGIN_LEFT = 90
  const MARGIN_RIGHT = 80
  const MARGIN_TOP = 70
  const MARGIN_BOTTOM = 110
  const WALL_THICKNESS = 8 // inches
  const WALL_DRAW_W = 14 // pixels for the wall hatching width
  const DOOR_THICKNESS = 4 // inches (panel thickness in side view)

  // Scaling helper: inches to pixels
  const s = (inches) => inches * scale

  // Compute drawing extents
  const layout = useMemo(() => {
    // Vertical extent: from floor up to top of headroom (or shaft, whichever higher)
    const aboveDoor = Math.max(g.headroomMin, g.clShaft + 6)
    const totalVertical = g.doorH + aboveDoor
    // Horizontal extent: wall + backroom
    const totalHorizontal = WALL_THICKNESS + g.backroom + 12

    const contentW = s(totalHorizontal)
    const contentH = s(totalVertical)

    const svgW = MARGIN_LEFT + contentW + MARGIN_RIGHT
    const svgH = MARGIN_TOP + contentH + MARGIN_BOTTOM

    // Origin: top-left of door opening (inside face of wall at top of door)
    const originX = MARGIN_LEFT + WALL_DRAW_W
    const originY = MARGIN_TOP + s(aboveDoor)

    return { svgW, svgH, originX, originY, aboveDoor, contentW, contentH }
  }, [g, scale])

  const { svgW, svgH, originX, originY } = layout

  // Floor Y = origin + door height
  const floorY = originY + s(g.doorH)

  // Curve center and geometry for quarter-circle track
  const curveStartY = originY - (g.lift === 'high_lift' ? s(g.hl) : 0)
  const curveCX = originX + s(g.radius)
  const curveCY = curveStartY
  const horizontalTrackY = curveStartY - s(g.radius)
  const horizontalTrackStartX = originX + s(g.radius)
  const horizontalTrackEndX = originX + s(g.backroom)

  // Shaft Y position
  const shaftY = originY - s(g.clShaft)
  // UST Y
  const ustY = originY - s(g.ust)

  return (
    <div className="side-elevation-drawing bg-white border border-gray-300 rounded-lg overflow-hidden">
      <svg
        width={svgW}
        height={svgH}
        viewBox={`0 0 ${svgW} ${svgH}`}
        style={{ fontFamily: "'Courier New', monospace" }}
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
        <text x={svgW / 2} y="20" fontSize="14" fontWeight="bold" textAnchor="middle" fill="#000">
          {title}
        </text>
        <text x={svgW / 2} y="36" fontSize="10" textAnchor="middle" fill="#333">
          {g.trackTypeLabel}
        </text>
        {doorSeries && (
          <text x={svgW / 2} y="50" fontSize="9" textAnchor="middle" fill="#555">
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
        {/* Wall outline */}
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
          x={originX - WALL_DRAW_W - 8}
          y={originY + s(g.doorH / 2)}
          fontSize="10"
          fill="#000"
          textAnchor="middle"
          transform={`rotate(-90, ${originX - WALL_DRAW_W - 8}, ${originY + s(g.doorH / 2)})`}
          fontWeight="bold"
        >
          EXTERIOR
        </text>
        <text
          x={originX + s(g.backroom / 2)}
          y={floorY + 24}
          fontSize="10"
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
          y={originY - s(g.headroomMin) + 3}
          fontSize="7"
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
          fontSize="7"
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
      // Vertical lift: very tall vertical tracks, no horizontal
      elements.push(
        <g key="vert-tracks">
          {/* Vertical track - full height */}
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
          {/* Track label */}
          <text
            x={originX + s(DOOR_THICKNESS + 1 + g.tSize / 2)}
            y={originY - s((g.verticalTrackLen - g.doorH) / 2)}
            fontSize="7"
            fill="#555"
            textAnchor="middle"
            transform={`rotate(-90, ${originX + s(DOOR_THICKNESS + 1 + g.tSize / 2)}, ${originY - s((g.verticalTrackLen - g.doorH) / 2)})`}
          >
            VERTICAL TRACK
          </text>
        </g>
      )
    } else if (lift === 'lhr_front' || lift === 'lhr_rear') {
      // Low headroom: double track configuration
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
          {/* Outer vertical track (offset) */}
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
            y={originY - s(g.headroomMin) - 8}
            fontSize="7"
            fill="#555"
            textAnchor="middle"
          >
            {lift === 'lhr_front' ? 'LOW HEADROOM FRONT MOUNT' : 'LOW HEADROOM REAR MOUNT'}
          </text>
        </g>
      )
    } else {
      // Standard and High Lift: vertical track + curve + horizontal track
      const vtTop = lift === 'high_lift' ? originY - s(g.hl) : originY

      elements.push(
        <g key="std-tracks">
          {/* Vertical track - inner and outer lines */}
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
              {/* HL label */}
              <text
                x={originX + s(DOOR_THICKNESS + 1 + g.tSize + 3)}
                y={originY - s(g.hl / 2)}
                fontSize="7"
                fill="#000"
                textAnchor="start"
                transform={`rotate(-90, ${originX + s(DOOR_THICKNESS + 1 + g.tSize + 3)}, ${originY - s(g.hl / 2)})`}
              >
                HIGH LIFT {formatDim(g.hl)}
              </text>
            </g>
          )}

          {/* Quarter-circle curve (inner and outer arcs) */}
          {g.curveType !== 'none' && (
            <g key="curve">
              {/* Inner arc */}
              <path
                d={`M ${originX + s(DOOR_THICKNESS + 1)} ${vtTop}
                    A ${s(g.radius)} ${s(g.radius)} 0 0 0
                    ${originX + s(DOOR_THICKNESS + 1 + g.radius)} ${vtTop - s(g.radius)}`}
                fill="none"
                stroke="#000"
                strokeWidth="1"
              />
              {/* Outer arc */}
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
                y={vtTop - s(g.radius * 0.35) - 4}
                fontSize="7"
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
              {/* Rear hanger / end support */}
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
      // Door goes straight up - show dashed door above opening
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
            fontSize="6"
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
      // LHR: door sits horizontal near ceiling
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
            y={openY - s(DOOR_THICKNESS) - 3}
            fontSize="6"
            fill="#555"
            textAnchor="middle"
          >
            DOOR (OPEN)
          </text>
        </g>
      )
    }

    // Standard / High Lift: door horizontal along ceiling track
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
          y={trackCenterY - s(DOOR_THICKNESS / 2) - 3}
          fontSize="6"
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
      // LHR: shaft near ceiling level
      const sy = originY - s(g.headroomMin - 3)
      return (
        <g className="shaft-assembly">
          {/* Shaft line */}
          <line x1={originX + s(2)} y1={sy} x2={originX + s(18)} y2={sy}
            stroke="#000" strokeWidth="2" />
          {/* Drum */}
          <circle cx={originX + s(6)} cy={sy} r={drumR}
            fill="none" stroke="#000" strokeWidth="1" />
          {/* Spring coil representation */}
          <line x1={originX + s(8)} y1={sy - 2} x2={originX + s(16)} y2={sy - 2}
            stroke="#000" strokeWidth="1.5" />
          <line x1={originX + s(8)} y1={sy + 2} x2={originX + s(16)} y2={sy + 2}
            stroke="#000" strokeWidth="1.5" />
          {/* Cable */}
          <line x1={originX + s(6)} y1={sy + drumR}
            x2={originX + s(4)} y2={floorY - s(4)}
            stroke="#000" strokeWidth="0.75" strokeDasharray="4,2" />
          <text x={originX + s(10)} y={sy - 6} fontSize="6" fill="#555" textAnchor="middle">
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
          x2={originX + s(20)}
          y2={shaftY}
          stroke="#000"
          strokeWidth="2"
        />
        {/* Drum circle */}
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
          y={shaftY - 6}
          fontSize="6"
          fill="#555"
          textAnchor="middle"
        >
          TORSION SPRING &amp; SHAFT
        </text>
        <text
          x={originX + s(6)}
          y={shaftY + drumR + 10}
          fontSize="6"
          fill="#555"
          textAnchor="middle"
        >
          DRUM
        </text>
      </g>
    )
  }

  /**
   * Render dimension lines with tick marks
   */
  function renderDimensions() {
    const elements = []
    const lift = g.lift
    const tickLen = 4

    // Helper: draw a dimension line between two points with tick marks and a label
    function dimLine(key, x1, y1, x2, y2, label, color = '#000', offset = 0, side = 'right') {
      const isVertical = Math.abs(x1 - x2) < 1
      const isHorizontal = Math.abs(y1 - y2) < 1

      if (isVertical) {
        const x = x1 + offset
        const yMin = Math.min(y1, y2)
        const yMax = Math.max(y1, y2)
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
                <line x1={x1} y1={yMin} x2={x + (offset > 0 ? -2 : 2)} y2={yMin}
                  stroke={color} strokeWidth="0.3" strokeDasharray="2,2" />
                <line x1={x1} y1={yMax} x2={x + (offset > 0 ? -2 : 2)} y2={yMax}
                  stroke={color} strokeWidth="0.3" strokeDasharray="2,2" />
              </>
            )}
            {/* Label */}
            <text
              x={x + (side === 'right' ? 8 : -8)}
              y={(yMin + yMax) / 2}
              fontSize="8"
              fill={color}
              textAnchor={side === 'right' ? 'start' : 'end'}
              dominantBaseline="middle"
              transform={`rotate(-90, ${x + (side === 'right' ? 8 : -8)}, ${(yMin + yMax) / 2})`}
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
                <line x1={xMin} y1={y1} x2={xMin} y2={y + (offset > 0 ? -2 : 2)}
                  stroke={color} strokeWidth="0.3" strokeDasharray="2,2" />
                <line x1={xMax} y1={y1} x2={xMax} y2={y + (offset > 0 ? -2 : 2)}
                  stroke={color} strokeWidth="0.3" strokeDasharray="2,2" />
              </>
            )}
            {/* Label */}
            <text
              x={(xMin + xMax) / 2}
              y={y + (offset > 0 ? 12 : -6)}
              fontSize="8"
              fill={color}
              textAnchor="middle"
            >
              {label}
            </text>
          </g>
        )
      }
    }

    // Door Height dimension (right side)
    const dimX = originX + s(g.backroom) + 20
    dimLine('dim-doorH', dimX, originY, dimX, floorY,
      `DOOR HEIGHT: ${formatDim(g.doorH)}`, '#000', 15)

    // Headroom dimension (right side, further out)
    dimLine('dim-headroom', dimX, originY - s(g.headroomMin), dimX, originY,
      `MIN. HEADROOM: ${formatDim(g.headroomMin)}`, '#C00', 35)

    // UST dimension (small, right side)
    if (lift !== 'lhr_front' && lift !== 'lhr_rear') {
      dimLine('dim-ust', dimX, originY - s(g.ust), dimX, originY,
        `U.S.T.: ${formatDim(g.ust)}`, '#555', 55)
    }

    // CL Shaft dimension
    if (lift !== 'lhr_front' && lift !== 'lhr_rear') {
      // CL shaft indicator
      elements.push(
        <g key="cl-shaft">
          <line
            x1={originX - 4}
            y1={shaftY}
            x2={originX + s(20) + 5}
            y2={shaftY}
            stroke="#555"
            strokeWidth="0.3"
            strokeDasharray="4,3"
          />
          <text x={dimX + 65} y={originY - s(g.clShaft / 2)} fontSize="7" fill="#555"
            textAnchor="middle"
            transform={`rotate(-90, ${dimX + 65}, ${originY - s(g.clShaft / 2)})`}>
            CL SHAFT: {formatDim(g.clShaft)}
          </text>
          {/* Dimension ticks for CL shaft */}
          <line x1={dimX + 60} y1={originY} x2={dimX + 70} y2={originY} stroke="#555" strokeWidth="0.5" />
          <line x1={dimX + 65} y1={originY} x2={dimX + 65} y2={shaftY} stroke="#555" strokeWidth="0.5" />
          <line x1={dimX + 60} y1={shaftY} x2={dimX + 70} y2={shaftY} stroke="#555" strokeWidth="0.5" />
        </g>
      )
    }

    // High lift extra dimension
    if (lift === 'high_lift' && g.hl > 0) {
      dimLine('dim-hl', originX + s(DOOR_THICKNESS + g.tSize + 6), originY, originX + s(DOOR_THICKNESS + g.tSize + 6), originY - s(g.hl),
        `HIGH LIFT: ${formatDim(g.hl)}`, '#00C', 0)
    }

    // Backroom dimension (horizontal, above ceiling)
    dimLine('dim-backroom', originX, originY - s(g.headroomMin), originX + s(g.backroom), originY - s(g.headroomMin),
      `MIN. BACKROOM: ${formatDim(g.backroom)}`, '#000', -18)

    return <g className="dimensions">{elements}</g>
  }

  /**
   * Render panel cross-section callout (top-right)
   */
  function renderPanelCallout() {
    const boxX = svgW - MARGIN_RIGHT - 100
    const boxY = MARGIN_TOP
    const boxW = 90
    const boxH = 55

    return (
      <g className="panel-callout">
        <rect x={boxX} y={boxY} width={boxW} height={boxH}
          fill="#fff" stroke="#000" strokeWidth="0.75" />
        <text x={boxX + boxW / 2} y={boxY + 10} fontSize="7" fontWeight="bold"
          textAnchor="middle" fill="#000">
          PANEL SECTION
        </text>
        {/* Simplified panel cross-section */}
        {/* Outer steel skin */}
        <rect x={boxX + 10} y={boxY + 16} width={boxW - 20} height={3}
          fill="#bbb" stroke="#000" strokeWidth="0.5" />
        {/* Insulation core */}
        <rect x={boxX + 10} y={boxY + 19} width={boxW - 20} height={14}
          fill="url(#insulFill)" stroke="#000" strokeWidth="0.5" />
        {/* Inner steel skin */}
        <rect x={boxX + 10} y={boxY + 33} width={boxW - 20} height={3}
          fill="#bbb" stroke="#000" strokeWidth="0.5" />
        {/* Labels */}
        <text x={boxX + boxW - 8} y={boxY + 19} fontSize="5" fill="#555" textAnchor="end">STEEL</text>
        <text x={boxX + boxW - 8} y={boxY + 28} fontSize="5" fill="#555" textAnchor="end">INSUL.</text>
        <text x={boxX + boxW - 8} y={boxY + 37} fontSize="5" fill="#555" textAnchor="end">STEEL</text>
        {doorSeries && (
          <text x={boxX + boxW / 2} y={boxY + 48} fontSize="6" textAnchor="middle" fill="#333">
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
    const boxX = 12
    const boxY = svgH - MARGIN_BOTTOM + 10
    const boxW = 195
    const boxH = 72

    return (
      <g className="requirements-box">
        <rect x={boxX} y={boxY} width={boxW} height={boxH}
          fill="#f9f9f9" stroke="#000" strokeWidth="0.75" />
        <line x1={boxX} y1={boxY + 14} x2={boxX + boxW} y2={boxY + 14}
          stroke="#000" strokeWidth="0.5" />
        <text x={boxX + boxW / 2} y={boxY + 11} fontSize="8" fontWeight="bold"
          textAnchor="middle" fill="#000">
          CLEARANCE REQUIREMENTS
        </text>
        <text x={boxX + 8} y={boxY + 28} fontSize="8" fill="#000">
          Min. Headroom:
        </text>
        <text x={boxX + boxW - 8} y={boxY + 28} fontSize="8" fill="#000" textAnchor="end" fontWeight="bold">
          {formatDim(g.headroomMin)}
        </text>
        <text x={boxX + 8} y={boxY + 42} fontSize="8" fill="#000">
          Min. Backroom:
        </text>
        <text x={boxX + boxW - 8} y={boxY + 42} fontSize="8" fill="#000" textAnchor="end" fontWeight="bold">
          {formatDim(g.backroom)}
        </text>
        <text x={boxX + 8} y={boxY + 56} fontSize="8" fill="#000">
          Min. Sideroom (ea.):
        </text>
        <text x={boxX + boxW - 8} y={boxY + 56} fontSize="8" fill="#000" textAnchor="end" fontWeight="bold">
          {formatDim(g.sideroom)}
        </text>
        <text x={boxX + boxW / 2} y={boxY + 68} fontSize="6" textAnchor="middle" fill="#888">
          {g.liftLabel} LIFT | {g.radiusLabel}
        </text>
      </g>
    )
  }
}

export default SideElevationDrawing
