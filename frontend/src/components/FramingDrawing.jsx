/**
 * FramingDrawing Component
 * Professional architectural/shop drawing showing front-face framing view
 * (inside looking out) for garage door installation.
 *
 * Receives a `geometry` prop from the backend with exact Thermalex dimensions.
 *
 * ALL visual sizes (fonts, ticks, margins, offsets) are proportional to the
 * drawing size via a `baseUnit` derived from door dimensions and scale, so
 * labels never overlap even on large doors (e.g. 16'x16').
 */

import { useMemo } from 'react'

function FramingDrawing({
  width = 96,
  height = 84,
  trackRadius = 15,
  trackSize = 2,
  liftType = 'standard',
  geometry = null,
  doorSeries = '',
  doorType = 'residential',
  frameType = 'steel',
  mountType = 'bracket',
  scale = 0.5,
  title = 'FRAMING DRAWING',
}) {
  // ---------------------------------------------------------------------------
  // Resolve geometry — use backend values when available, otherwise approximate
  // ---------------------------------------------------------------------------
  const geo = useMemo(() => {
    const g = geometry || {}
    const dw = g.door_width ?? width
    const dh = g.door_height ?? height
    const ft = g.frame_type ?? frameType
    const fw = g.frame_width_inches ?? (ft === 'steel' ? 3 : 3.5)
    const sr = g.sideroom ?? 4.25
    const srAngle = g.sideroom_angle ?? 3.5
    const srBracket = g.sideroom_bracket ?? sr
    const cp = g.center_post ?? 8.5
    const ust = g.ust ?? 7.5
    const clShaft = g.cl_shaft ?? 14.5
    const hrMin = g.headroom_min ?? (trackRadius + 3)
    const br = g.backroom ?? (dh + 18)
    const vtl = g.vertical_track_length ?? dh
    const htl = g.horizontal_track_length ?? (br - trackRadius - 5)
    const tr = g.track_radius ?? trackRadius
    const ts = g.track_size ?? trackSize
    const lt = g.lift_type ?? liftType
    const mt = g.mount_type ?? mountType
    const ttl = g.track_type_label ?? 'STANDARD LIFT TRACKS'
    const rl = g.radius_label ?? `${tr}" RADIUS`

    return {
      doorWidth: dw,
      doorHeight: dh,
      frameType: ft,
      frameWidth: fw,
      sideroom: sr,
      sideroomAngle: srAngle,
      sideroomBracket: srBracket,
      centerPost: cp,
      ust,
      clShaft,
      headroomMin: hrMin,
      backroom: br,
      verticalTrackLength: vtl,
      horizontalTrackLength: htl,
      trackRadius: tr,
      trackSize: ts,
      liftType: lt,
      mountType: mt,
      trackTypeLabel: ttl,
      radiusLabel: rl,
    }
  }, [geometry, width, height, trackRadius, trackSize, liftType, frameType, mountType])

  // ---------------------------------------------------------------------------
  // Proportional base unit and derived sizes
  // ---------------------------------------------------------------------------
  const ui = useMemo(() => {
    const doorW = geo.doorWidth
    const doorH = geo.doorHeight
    const baseUnit = Math.max(5, Math.min(12, Math.sqrt(Math.max(doorW, doorH) * scale) * 0.8))

    const fontSize = {
      title: baseUnit * 1.8,
      subtitle: baseUnit * 1.3,
      label: baseUnit * 1.1,
      small: baseUnit * 0.85,
    }
    const tickLen = baseUnit * 0.5
    const dimLineSpacing = baseUnit * 3
    const margin = {
      top: Math.max(65, baseUnit * 8),
      right: Math.max(70, baseUnit * 9),
      bottom: Math.max(70, baseUnit * 10),
      left: Math.max(70, baseUnit * 9),
    }
    const leaderLen = baseUnit * 2.5
    const calloutScale = Math.max(1.5, baseUnit * 0.3)

    return { baseUnit, fontSize, tickLen, dimLineSpacing, margin, leaderLen, calloutScale }
  }, [geo.doorWidth, geo.doorHeight, scale])

  // ---------------------------------------------------------------------------
  // Derived layout values
  // ---------------------------------------------------------------------------
  const layout = useMemo(() => {
    const dw = geo.doorWidth
    const dh = geo.doorHeight
    const fw = geo.frameWidth
    const sr = geo.sideroom
    const hrMin = geo.headroomMin
    const clShaft = geo.clShaft
    const ts = geo.trackSize
    const tr = geo.trackRadius

    const shaftY = clShaft
    const wallThickness = 8
    const headerHeight = 6
    const topClearance = Math.max(hrMin, shaftY) + headerHeight + 10

    const { margin, dimLineSpacing } = ui

    // Content size in inches
    const contentW = dw + (fw + wallThickness + sr) * 2
    const contentH = dh + topClearance + 12

    // SVG dimensions (viewBox units)
    const svgW = Math.max(500, contentW * scale + margin.left + margin.right)
    const svgH = contentH * scale + margin.top + margin.bottom

    // Origin = top-left corner of door opening in SVG coords
    const originX = margin.left + (fw + wallThickness + sr) * scale
    const originY = margin.top + topClearance * scale

    return {
      dw, dh, fw, sr, hrMin, clShaft, ts, tr,
      shaftY, wallThickness, headerHeight, topClearance,
      margin, contentW, contentH, svgW, svgH,
      originX, originY, dimLineSpacing,
    }
  }, [geo, scale, ui])

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  const s = (inches) => inches * scale

  /** Format inches to feet-inches string */
  const formatDim = (inches) => {
    if (inches == null) return ''
    const negative = inches < 0
    const abs = Math.abs(inches)
    const ft = Math.floor(abs / 12)
    const rem = abs % 12
    const whole = Math.floor(rem)
    const frac = rem - whole
    let fracStr = ''
    if (frac >= 0.875) {
      return formatDim((negative ? -1 : 1) * ((ft * 12) + whole + 1))
    } else if (frac >= 0.625) {
      fracStr = '\u00BE'
    } else if (frac >= 0.375) {
      fracStr = '\u00BD'
    } else if (frac >= 0.125) {
      fracStr = '\u00BC'
    }

    const sign = negative ? '-' : ''
    const inchVal = `${whole}${fracStr}"`
    if (ft === 0) return `${sign}${inchVal}`
    if (whole === 0 && !fracStr) return `${sign}${ft}'-0"`
    return `${sign}${ft}'-${inchVal}`
  }

  const { dw, dh, fw, sr, ts, tr } = layout
  const ox = layout.originX
  const oy = layout.originY
  const isSteel = geo.frameType === 'steel'
  const jambLabel = isSteel ? 'STEEL JAMB' : 'WOOD JAMB'
  const applicationLabel = isSteel ? 'STEEL JAMB APPLICATION' : 'WOOD JAMB APPLICATION'

  // Shorthand for proportional sizes
  const { fontSize, tickLen, dimLineSpacing, leaderLen, calloutScale } = ui

  // Track flag positions (evenly along vertical track)
  const flagCount = 4
  const flagPositions = Array.from({ length: flagCount }, (_, i) =>
    (i / (flagCount - 1)) * (dh - 8) + 2
  )

  // Shaft position
  const shaftYPx = oy - s(layout.clShaft)

  return (
    <div className="framing-drawing bg-white border border-gray-300 rounded-lg overflow-hidden">
      <svg
        viewBox={`0 0 ${layout.svgW} ${layout.svgH}`}
        style={{
          fontFamily: "'Segoe UI', Arial, Helvetica, sans-serif",
          width: '100%',
          maxWidth: `${layout.svgW}px`,
        }}
      >
        <defs>
          {/* Concrete / masonry hatch — diagonal lines */}
          <pattern id="fd-concreteHatch" patternUnits="userSpaceOnUse" width="6" height="6"
            patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="#888" strokeWidth="0.5" />
          </pattern>

          {/* Wood grain — wavy horizontal lines */}
          <pattern id="fd-woodGrain" patternUnits="userSpaceOnUse" width="24" height="6">
            <path d="M0,3 Q6,1 12,3 T24,3" stroke="#8B6914" strokeWidth="0.4" fill="none" />
            <path d="M0,5 Q6,3.5 12,5 T24,5" stroke="#A0782C" strokeWidth="0.3" fill="none" />
          </pattern>

          {/* Steel fill — solid light gray */}
          <pattern id="fd-steelFill" patternUnits="userSpaceOnUse" width="4" height="4">
            <rect width="4" height="4" fill="#C0C0C0" />
          </pattern>

          {/* Steel jamb fill — slightly darker */}
          <pattern id="fd-steelJamb" patternUnits="userSpaceOnUse" width="4" height="4">
            <rect width="4" height="4" fill="#B0B0B0" />
            <line x1="0" y1="0" x2="4" y2="4" stroke="#999" strokeWidth="0.3" />
          </pattern>
        </defs>

        {/* ================================================================ */}
        {/* TITLE BLOCK                                                      */}
        {/* ================================================================ */}
        <g>
          <text x={layout.svgW / 2} y={fontSize.title + 4} fontSize={fontSize.title} fontWeight="bold"
            textAnchor="middle" fill="#111">
            {title}
          </text>
          <text x={layout.svgW / 2} y={fontSize.title + 4 + fontSize.subtitle * 1.5}
            fontSize={fontSize.subtitle} textAnchor="middle" fill="#444">
            {applicationLabel}
          </text>
          <text x={layout.svgW / 2} y={fontSize.title + 4 + fontSize.subtitle * 1.5 + fontSize.label * 1.5}
            fontSize={fontSize.label} textAnchor="middle" fill="#666">
            DOOR FACE: INSIDE LOOKING OUT
          </text>
          {doorSeries && (
            <text x={layout.svgW / 2}
              y={fontSize.title + 4 + fontSize.subtitle * 1.5 + fontSize.label * 3}
              fontSize={fontSize.label} textAnchor="middle" fill="#666">
              Series: {doorSeries}
            </text>
          )}
        </g>

        {/* ================================================================ */}
        {/* FLOOR LINE                                                       */}
        {/* ================================================================ */}
        <line
          x1={ox - s(fw + layout.wallThickness + 15)}
          y1={oy + s(dh)}
          x2={ox + s(dw + fw + layout.wallThickness + 15)}
          y2={oy + s(dh)}
          stroke="#111" strokeWidth="2.5"
        />
        {/* Floor hatch below line */}
        <g>
          {Array.from({ length: Math.ceil((dw + 2 * (fw + layout.wallThickness + 15)) / 4) }, (_, i) => {
            const lx = ox - s(fw + layout.wallThickness + 15) + i * s(4)
            const ly = oy + s(dh)
            return (
              <line key={`fh-${i}`} x1={lx} y1={ly + 1} x2={lx + s(3)} y2={ly + s(3)}
                stroke="#888" strokeWidth="0.5" />
            )
          })}
        </g>
        <text x={ox - s(fw + layout.wallThickness + 18)} y={oy + s(dh) + fontSize.small * 0.5}
          fontSize={fontSize.small} fill="#666" textAnchor="end">
          FLOOR LINE
        </text>

        {/* ================================================================ */}
        {/* WALL SECTIONS (hatched masonry)                                   */}
        {/* ================================================================ */}
        {/* Left wall */}
        <rect
          x={ox - s(fw + layout.wallThickness)}
          y={oy - s(layout.topClearance - 4)}
          width={s(layout.wallThickness)}
          height={s(dh + layout.topClearance - 4 + 8)}
          fill="url(#fd-concreteHatch)" stroke="#333" strokeWidth="1"
        />
        {/* Right wall */}
        <rect
          x={ox + s(dw + fw)}
          y={oy - s(layout.topClearance - 4)}
          width={s(layout.wallThickness)}
          height={s(dh + layout.topClearance - 4 + 8)}
          fill="url(#fd-concreteHatch)" stroke="#333" strokeWidth="1"
        />

        {/* ================================================================ */}
        {/* JAMBS                                                            */}
        {/* ================================================================ */}
        {/* Left jamb */}
        <rect
          x={ox - s(fw)}
          y={oy - s(layout.topClearance - layout.headerHeight - 4)}
          width={s(fw)}
          height={s(dh + layout.topClearance - layout.headerHeight - 4)}
          fill={isSteel ? 'url(#fd-steelJamb)' : 'url(#fd-woodGrain)'}
          stroke="#333" strokeWidth="1"
        />
        {/* Right jamb */}
        <rect
          x={ox + s(dw)}
          y={oy - s(layout.topClearance - layout.headerHeight - 4)}
          width={s(fw)}
          height={s(dh + layout.topClearance - layout.headerHeight - 4)}
          fill={isSteel ? 'url(#fd-steelJamb)' : 'url(#fd-woodGrain)'}
          stroke="#333" strokeWidth="1"
        />
        {/* Jamb labels */}
        <text
          x={ox - s(fw / 2)}
          y={oy + s(dh / 2)}
          fontSize={fontSize.small} fill="#333" textAnchor="middle"
          transform={`rotate(-90, ${ox - s(fw / 2)}, ${oy + s(dh / 2)})`}
        >
          {jambLabel}
        </text>
        <text
          x={ox + s(dw + fw / 2)}
          y={oy + s(dh / 2)}
          fontSize={fontSize.small} fill="#333" textAnchor="middle"
          transform={`rotate(-90, ${ox + s(dw + fw / 2)}, ${oy + s(dh / 2)})`}
        >
          {jambLabel}
        </text>

        {/* Weather stripping labels */}
        <text
          x={ox - s(fw) - fontSize.small * 0.3}
          y={oy + s(dh * 0.7)}
          fontSize={fontSize.small * 0.7} fill="#888" textAnchor="end"
          transform={`rotate(-90, ${ox - s(fw) - fontSize.small * 0.3}, ${oy + s(dh * 0.7)})`}
        >
          WEATHER STRIPPING
        </text>
        <text
          x={ox + s(dw + fw) + fontSize.small * 0.3}
          y={oy + s(dh * 0.3)}
          fontSize={fontSize.small * 0.7} fill="#888" textAnchor="start"
          transform={`rotate(90, ${ox + s(dw + fw) + fontSize.small * 0.3}, ${oy + s(dh * 0.3)})`}
        >
          WEATHER STRIPPING
        </text>

        {/* ================================================================ */}
        {/* HEADER                                                           */}
        {/* ================================================================ */}
        <rect
          x={ox - s(fw + 4)}
          y={oy - s(layout.topClearance - 4)}
          width={s(dw + fw * 2 + 8)}
          height={s(layout.headerHeight)}
          fill={isSteel ? 'url(#fd-steelJamb)' : 'url(#fd-woodGrain)'}
          stroke="#333" strokeWidth="1.5"
        />
        <text
          x={ox + s(dw / 2)}
          y={oy - s(layout.topClearance - 4 - layout.headerHeight / 2) + fontSize.label * 0.35}
          fontSize={fontSize.label} textAnchor="middle" fill="#333" fontWeight="bold"
        >
          HEADER
        </text>

        {/* ================================================================ */}
        {/* DOOR OPENING (dashed outline)                                    */}
        {/* ================================================================ */}
        <rect
          x={ox} y={oy}
          width={s(dw)} height={s(dh)}
          fill="none" stroke="#0055AA" strokeWidth="1.2" strokeDasharray="8,4"
        />
        <text
          x={ox + s(dw / 2)} y={oy + s(dh / 2) + fontSize.label * 0.35}
          fontSize={fontSize.label} textAnchor="middle" fill="#0055AA" opacity="0.6"
        >
          DOOR OPENING
        </text>

        {/* ================================================================ */}
        {/* VERTICAL TRACKS                                                  */}
        {/* ================================================================ */}
        {/* Left vertical track */}
        <rect
          x={ox + s(1)} y={oy}
          width={s(ts)} height={s(geo.verticalTrackLength)}
          fill="url(#fd-steelFill)" stroke="#333" strokeWidth="0.8"
        />
        {/* Right vertical track */}
        <rect
          x={ox + s(dw - 1 - ts)} y={oy}
          width={s(ts)} height={s(geo.verticalTrackLength)}
          fill="url(#fd-steelFill)" stroke="#333" strokeWidth="0.8"
        />

        {/* Track mounting flags */}
        {flagPositions.map((yPos, i) => (
          <g key={`flags-${i}`}>
            {/* Left flag */}
            <rect
              x={ox - s(0.5)} y={oy + s(yPos)}
              width={s(ts + 2)} height={s(3)}
              fill="#888" stroke="#333" strokeWidth="0.5" rx="0.5"
            />
            {/* Right flag */}
            <rect
              x={ox + s(dw - ts - 1.5)} y={oy + s(yPos)}
              width={s(ts + 2)} height={s(3)}
              fill="#888" stroke="#333" strokeWidth="0.5" rx="0.5"
            />
          </g>
        ))}

        {/* ================================================================ */}
        {/* TRACK CURVES (quarter-circle arcs)                               */}
        {/* ================================================================ */}
        {/* Left curve */}
        <path
          d={`M ${ox + s(1 + ts / 2)} ${oy}
              A ${s(tr)} ${s(tr)} 0 0 1
              ${ox + s(1 + ts / 2 + tr)} ${oy - s(tr)}`}
          fill="none" stroke="#333" strokeWidth={s(ts) * 0.6} opacity="0.5"
        />
        {/* Right curve */}
        <path
          d={`M ${ox + s(dw - 1 - ts / 2)} ${oy}
              A ${s(tr)} ${s(tr)} 0 0 0
              ${ox + s(dw - 1 - ts / 2 - tr)} ${oy - s(tr)}`}
          fill="none" stroke="#333" strokeWidth={s(ts) * 0.6} opacity="0.5"
        />

        {/* Radius label on left curve */}
        <text
          x={ox + s(1 + ts / 2 + tr / 2) + fontSize.small * 0.3}
          y={oy - s(tr / 2) - fontSize.small * 0.4}
          fontSize={fontSize.small} fill="#555"
        >
          {geo.radiusLabel}
        </text>

        {/* ================================================================ */}
        {/* HORIZONTAL TRACKS (dashed, receding into building)               */}
        {/* ================================================================ */}
        {/* Left horizontal */}
        <line
          x1={ox + s(1 + ts / 2 + tr)} y1={oy - s(tr)}
          x2={ox + s(1 + ts / 2 + tr + 30)} y2={oy - s(tr)}
          stroke="#333" strokeWidth={s(ts) * 0.5}
          strokeDasharray="6,4" opacity="0.35"
        />
        {/* Right horizontal */}
        <line
          x1={ox + s(dw - 1 - ts / 2 - tr)} y1={oy - s(tr)}
          x2={ox + s(dw - 1 - ts / 2 - tr - 30)} y2={oy - s(tr)}
          stroke="#333" strokeWidth={s(ts) * 0.5}
          strokeDasharray="6,4" opacity="0.35"
        />

        {/* Track type label */}
        <text
          x={ox + s(dw / 2)} y={oy - s(tr) - fontSize.small * 0.5}
          fontSize={fontSize.small} textAnchor="middle" fill="#555"
        >
          {geo.trackTypeLabel}
        </text>

        {/* ================================================================ */}
        {/* SPRING ASSEMBLY                                                  */}
        {/* ================================================================ */}
        <g className="spring-assembly">
          {/* Torsion shaft (thick horizontal line) */}
          <line
            x1={ox + s(3)} y1={shaftYPx}
            x2={ox + s(dw - 3)} y2={shaftYPx}
            stroke="#222" strokeWidth="2.5"
          />

          {/* Left cable drum */}
          <circle
            cx={ox + s(5)} cy={shaftYPx} r={s(3.5)}
            fill="#777" stroke="#333" strokeWidth="1"
          />
          <text x={ox + s(5)} y={shaftYPx + s(3.5) + fontSize.small * 1.1}
            fontSize={fontSize.small * 0.75} textAnchor="middle" fill="#666">DRUM</text>

          {/* Right cable drum */}
          <circle
            cx={ox + s(dw - 5)} cy={shaftYPx} r={s(3.5)}
            fill="#777" stroke="#333" strokeWidth="1"
          />
          <text x={ox + s(dw - 5)} y={shaftYPx + s(3.5) + fontSize.small * 1.1}
            fontSize={fontSize.small * 0.75} textAnchor="middle" fill="#666">DRUM</text>

          {/* Springs (red/maroon rectangles) */}
          <rect
            x={ox + s(dw / 2 - 22)} y={shaftYPx - s(2)}
            width={s(20)} height={s(4)}
            fill="#8B1A1A" stroke="#333" strokeWidth="0.5" rx="1.5"
          />
          <rect
            x={ox + s(dw / 2 + 2)} y={shaftYPx - s(2)}
            width={s(20)} height={s(4)}
            fill="#8B1A1A" stroke="#333" strokeWidth="0.5" rx="1.5"
          />
          {/* Spring coil indication lines */}
          {Array.from({ length: 8 }, (_, i) => (
            <line key={`sc-l-${i}`}
              x1={ox + s(dw / 2 - 20 + i * 2.5)} y1={shaftYPx - s(2)}
              x2={ox + s(dw / 2 - 20 + i * 2.5)} y2={shaftYPx + s(2)}
              stroke="#B33" strokeWidth="0.3"
            />
          ))}
          {Array.from({ length: 8 }, (_, i) => (
            <line key={`sc-r-${i}`}
              x1={ox + s(dw / 2 + 4 + i * 2.5)} y1={shaftYPx - s(2)}
              x2={ox + s(dw / 2 + 4 + i * 2.5)} y2={shaftYPx + s(2)}
              stroke="#B33" strokeWidth="0.3"
            />
          ))}

          {/* Center bearing plate */}
          <rect
            x={ox + s(dw / 2 - 2.5)} y={shaftYPx - s(4)}
            width={s(5)} height={s(8)}
            fill="#555" stroke="#333" strokeWidth="1"
          />
          <text x={ox + s(dw / 2)} y={shaftYPx + s(4) + fontSize.small * 1.1}
            fontSize={fontSize.small * 0.75} textAnchor="middle" fill="#666">CENTER BEARING</text>

          {/* SPRING ASSEMBLY label */}
          <text x={ox + s(dw / 2)} y={shaftYPx - s(6)}
            fontSize={fontSize.label} textAnchor="middle" fill="#444" fontWeight="bold">
            SPRING ASSEMBLY
          </text>
        </g>

        {/* ================================================================ */}
        {/* CENTERLINE OF SHAFT — label with leader line                     */}
        {/* ================================================================ */}
        <g>
          {/* Dashed centerline marker */}
          <line
            x1={ox - s(fw) - leaderLen * 0.4} y1={shaftYPx}
            x2={ox + s(2)} y2={shaftYPx}
            stroke="#333" strokeWidth="0.5" strokeDasharray="4,2"
          />
          {/* Leader line from label */}
          <line
            x1={ox - s(fw + layout.wallThickness) - leaderLen * 0.8} y1={shaftYPx - leaderLen}
            x2={ox - s(fw) - leaderLen * 0.4} y2={shaftYPx}
            stroke="#333" strokeWidth="0.5"
          />
          {/* Arrow dot at end */}
          <circle cx={ox - s(fw) - leaderLen * 0.4} cy={shaftYPx} r="1.5" fill="#333" />
          <text
            x={ox - s(fw + layout.wallThickness) - leaderLen * 0.8 - fontSize.small * 0.3}
            y={shaftYPx - leaderLen - fontSize.small * 0.5}
            fontSize={fontSize.small} fill="#333" textAnchor="end" fontWeight="bold"
          >
            CENTERLINE OF SHAFT
          </text>
        </g>

        {/* ================================================================ */}
        {/* DIMENSION LINES                                                  */}
        {/* ================================================================ */}

        {/* --- Door Width (below floor line) --- */}
        {(() => {
          const dimY = oy + s(dh) + dimLineSpacing
          const x1 = ox
          const x2 = ox + s(dw)
          return (
            <g className="dim-door-width">
              {/* Extension lines */}
              <line x1={x1} y1={oy + s(dh) + 3} x2={x1} y2={dimY + tickLen}
                stroke="#333" strokeWidth="0.4" />
              <line x1={x2} y1={oy + s(dh) + 3} x2={x2} y2={dimY + tickLen}
                stroke="#333" strokeWidth="0.4" />
              {/* Dimension line */}
              <line x1={x1} y1={dimY} x2={x2} y2={dimY}
                stroke="#333" strokeWidth="0.6" />
              {/* Tick marks */}
              <line x1={x1} y1={dimY - tickLen} x2={x1} y2={dimY + tickLen}
                stroke="#333" strokeWidth="0.8" />
              <line x1={x2} y1={dimY - tickLen} x2={x2} y2={dimY + tickLen}
                stroke="#333" strokeWidth="0.8" />
              {/* Label */}
              <text x={(x1 + x2) / 2} y={dimY + tickLen + fontSize.label * 1.2}
                fontSize={fontSize.label} textAnchor="middle" fill="#111" fontWeight="bold">
                {formatDim(dw)}
              </text>
              <text x={(x1 + x2) / 2} y={dimY + tickLen + fontSize.label * 1.2 + fontSize.small * 1.3}
                fontSize={fontSize.small} textAnchor="middle" fill="#666">
                DOOR WIDTH
              </text>
            </g>
          )
        })()}

        {/* --- Door Height (right side) --- */}
        {(() => {
          const dimX = ox + s(dw + fw + layout.wallThickness) + dimLineSpacing
          const y1 = oy
          const y2 = oy + s(dh)
          return (
            <g className="dim-door-height">
              {/* Extension lines */}
              <line x1={ox + s(dw) + 3} y1={y1} x2={dimX + tickLen} y2={y1}
                stroke="#333" strokeWidth="0.4" />
              <line x1={ox + s(dw) + 3} y1={y2} x2={dimX + tickLen} y2={y2}
                stroke="#333" strokeWidth="0.4" />
              {/* Dimension line */}
              <line x1={dimX} y1={y1} x2={dimX} y2={y2}
                stroke="#333" strokeWidth="0.6" />
              {/* Tick marks */}
              <line x1={dimX - tickLen} y1={y1} x2={dimX + tickLen} y2={y1}
                stroke="#333" strokeWidth="0.8" />
              <line x1={dimX - tickLen} y1={y2} x2={dimX + tickLen} y2={y2}
                stroke="#333" strokeWidth="0.8" />
              {/* Label */}
              <text
                x={dimX + tickLen + fontSize.label * 0.8} y={(y1 + y2) / 2 + fontSize.label * 0.35}
                fontSize={fontSize.label} fill="#111" fontWeight="bold"
                transform={`rotate(-90, ${dimX + tickLen + fontSize.label * 0.8}, ${(y1 + y2) / 2})`}
                textAnchor="middle"
              >
                {formatDim(dh)}
              </text>
              <text
                x={dimX + tickLen + fontSize.label * 0.8 + fontSize.small * 1.5}
                y={(y1 + y2) / 2 + fontSize.small * 0.35}
                fontSize={fontSize.small} fill="#666"
                transform={`rotate(-90, ${dimX + tickLen + fontSize.label * 0.8 + fontSize.small * 1.5}, ${(y1 + y2) / 2})`}
                textAnchor="middle"
              >
                DOOR HEIGHT
              </text>
            </g>
          )
        })()}

        {/* --- CL Shaft Height (left side, floor to shaft) --- */}
        {(() => {
          const dimX = ox - s(fw + layout.wallThickness) - dimLineSpacing
          const y1 = shaftYPx
          const y2 = oy + s(dh)
          const clHeight = dh + geo.clShaft
          return (
            <g className="dim-cl-shaft">
              {/* Extension lines */}
              <line x1={dimX - tickLen} y1={y1} x2={ox - s(fw)} y2={y1}
                stroke="#333" strokeWidth="0.4" />
              <line x1={dimX - tickLen} y1={y2} x2={ox - s(fw + layout.wallThickness)} y2={y2}
                stroke="#333" strokeWidth="0.4" />
              {/* Dimension line */}
              <line x1={dimX} y1={y1} x2={dimX} y2={y2}
                stroke="#333" strokeWidth="0.6" />
              {/* Tick marks */}
              <line x1={dimX - tickLen} y1={y1} x2={dimX + tickLen} y2={y1}
                stroke="#333" strokeWidth="0.8" />
              <line x1={dimX - tickLen} y1={y2} x2={dimX + tickLen} y2={y2}
                stroke="#333" strokeWidth="0.8" />
              {/* Label */}
              <text
                x={dimX - tickLen - fontSize.label * 0.5} y={(y1 + y2) / 2 + fontSize.label * 0.35}
                fontSize={fontSize.label} fill="#111" fontWeight="bold"
                transform={`rotate(-90, ${dimX - tickLen - fontSize.label * 0.5}, ${(y1 + y2) / 2})`}
                textAnchor="middle"
              >
                {formatDim(clHeight)}
              </text>
              <text
                x={dimX - tickLen - fontSize.label * 0.5 - fontSize.small * 1.5}
                y={(y1 + y2) / 2 + fontSize.small * 0.35}
                fontSize={fontSize.small} fill="#666"
                transform={`rotate(-90, ${dimX - tickLen - fontSize.label * 0.5 - fontSize.small * 1.5}, ${(y1 + y2) / 2})`}
                textAnchor="middle"
              >
                CL SHAFT
              </text>
            </g>
          )
        })()}

        {/* --- Sideroom dimensions (small, above jambs) --- */}
        {(() => {
          const dimY = oy - s(layout.topClearance - layout.headerHeight - 6) - fontSize.small
          // Left sideroom: from wall inner edge to door opening edge
          const lx1 = ox - s(fw)
          const lx2 = ox
          // Right sideroom
          const rx1 = ox + s(dw)
          const rx2 = ox + s(dw + fw)
          return (
            <g className="dim-sideroom">
              {/* Left */}
              <line x1={lx1} y1={dimY} x2={lx2} y2={dimY}
                stroke="#333" strokeWidth="0.4" />
              <line x1={lx1} y1={dimY - tickLen} x2={lx1} y2={dimY + tickLen}
                stroke="#333" strokeWidth="0.6" />
              <line x1={lx2} y1={dimY - tickLen} x2={lx2} y2={dimY + tickLen}
                stroke="#333" strokeWidth="0.6" />
              <text x={(lx1 + lx2) / 2} y={dimY - tickLen - fontSize.small * 0.3}
                fontSize={fontSize.small} textAnchor="middle" fill="#333">
                {formatDim(fw)}
              </text>

              {/* Right */}
              <line x1={rx1} y1={dimY} x2={rx2} y2={dimY}
                stroke="#333" strokeWidth="0.4" />
              <line x1={rx1} y1={dimY - tickLen} x2={rx1} y2={dimY + tickLen}
                stroke="#333" strokeWidth="0.6" />
              <line x1={rx2} y1={dimY - tickLen} x2={rx2} y2={dimY + tickLen}
                stroke="#333" strokeWidth="0.6" />
              <text x={(rx1 + rx2) / 2} y={dimY - tickLen - fontSize.small * 0.3}
                fontSize={fontSize.small} textAnchor="middle" fill="#333">
                {formatDim(fw)}
              </text>

              {/* Sideroom label (wider, includes wall) */}
              <text x={ox - s(fw + layout.wallThickness / 2)} y={dimY - tickLen - fontSize.small * 1.6}
                fontSize={fontSize.small} textAnchor="middle" fill="#666">
                SIDEROOM: {formatDim(sr)} MIN
              </text>
            </g>
          )
        })()}

        {/* --- Headroom minimum label --- */}
        {(() => {
          const hrLabelX = ox + s(dw) + dimLineSpacing * 0.5
          const hrTop = oy - s(geo.headroomMin)
          return (
            <g className="dim-headroom">
              {/* Small bracket */}
              <line x1={hrLabelX} y1={hrTop} x2={hrLabelX} y2={oy}
                stroke="#666" strokeWidth="0.4" strokeDasharray="3,2" />
              <line x1={hrLabelX - tickLen} y1={hrTop} x2={hrLabelX + tickLen} y2={hrTop}
                stroke="#666" strokeWidth="0.6" />
              <line x1={hrLabelX - tickLen} y1={oy} x2={hrLabelX + tickLen} y2={oy}
                stroke="#666" strokeWidth="0.6" />
              <text
                x={hrLabelX + tickLen + fontSize.small * 0.5}
                y={(hrTop + oy) / 2 + fontSize.small * 0.35}
                fontSize={fontSize.small} fill="#666"
                transform={`rotate(-90, ${hrLabelX + tickLen + fontSize.small * 0.5}, ${(hrTop + oy) / 2})`}
                textAnchor="middle"
              >
                HEADROOM MIN: {formatDim(geo.headroomMin)}
              </text>
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* JAMB DETAIL CALLOUT (bottom-left corner)                         */}
        {/* ================================================================ */}
        {(() => {
          const detailX = fontSize.label * 1.5
          const detailY = layout.svgH - ui.baseUnit * 10
          const ds = calloutScale
          return (
            <g className="jamb-detail" transform={`translate(${detailX}, ${detailY})`}>
              <text x="0" y={-fontSize.small * 0.5} fontSize={fontSize.label} fontWeight="bold" fill="#333">
                JAMB DETAIL (SECTION)
              </text>
              <rect x="0" y="0" width={35 * ds} height={25 * ds}
                fill="none" stroke="#333" strokeWidth="0.8" />

              {/* Wall section */}
              <rect x={0} y={0} width={8 * ds} height={25 * ds}
                fill="url(#fd-concreteHatch)" stroke="#333" strokeWidth="0.5" />

              {/* Jamb section */}
              <rect x={8 * ds} y={2 * ds} width={fw * ds} height={21 * ds}
                fill={isSteel ? 'url(#fd-steelJamb)' : 'url(#fd-woodGrain)'}
                stroke="#333" strokeWidth="0.5" />

              {/* Weather seal strip */}
              <rect x={(8 + fw) * ds} y={4 * ds} width={1.5 * ds} height={18 * ds}
                fill="#444" stroke="#333" strokeWidth="0.3" />
              <text x={(8 + fw + 1.5) * ds + fontSize.small * 0.4} y={10 * ds}
                fontSize={fontSize.small * 0.65} fill="#666">WEATHER SEAL</text>

              {/* End cap */}
              <rect x={(8 + fw + 2) * ds} y={20 * ds} width={4 * ds} height={3 * ds}
                fill="#999" stroke="#333" strokeWidth="0.3" />
              <text x={(8 + fw + 7) * ds} y={22 * ds}
                fontSize={fontSize.small * 0.65} fill="#666">END CAP</text>

              {/* Bottom bracket indicator */}
              <rect x={(8 + fw + 2) * ds} y={1 * ds} width={5 * ds} height={4 * ds}
                fill="#888" stroke="#333" strokeWidth="0.3" />
              <text x={(8 + fw + 8) * ds} y={4 * ds}
                fontSize={fontSize.small * 0.65} fill="#666">BOTTOM BRACKET</text>

              {/* Astragal */}
              <rect x={(8 + fw + 2) * ds} y={24 * ds} width={8 * ds} height={1 * ds}
                fill="#666" stroke="#333" strokeWidth="0.3" />
              <text x={(8 + fw + 11) * ds} y={25 * ds}
                fontSize={fontSize.small * 0.65} fill="#666">ASTRAGAL</text>
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* LEGEND                                                           */}
        {/* ================================================================ */}
        {(() => {
          const legendX = layout.svgW - ui.baseUnit * 16
          const legendY = layout.svgH - ui.baseUnit * 9
          const swatchW = fontSize.label * 1.4
          const swatchH = fontSize.small * 0.9
          const rowH = fontSize.small * 1.6
          return (
            <g transform={`translate(${legendX}, ${legendY})`}>
              <text fontSize={fontSize.label} fontWeight="bold" fill="#333">LEGEND</text>
              <g transform={`translate(0, ${rowH * 0.7})`}>
                <rect width={swatchW} height={swatchH}
                  fill={isSteel ? 'url(#fd-steelJamb)' : 'url(#fd-woodGrain)'}
                  stroke="#333" strokeWidth="0.5" />
                <text x={swatchW + fontSize.small * 0.4} y={swatchH * 0.8}
                  fontSize={fontSize.small} fill="#444">
                  {isSteel ? 'Steel Framing' : 'Wood Framing'}
                </text>
              </g>
              <g transform={`translate(0, ${rowH * 0.7 + rowH})`}>
                <rect width={swatchW} height={swatchH} fill="url(#fd-concreteHatch)"
                  stroke="#333" strokeWidth="0.5" />
                <text x={swatchW + fontSize.small * 0.4} y={swatchH * 0.8}
                  fontSize={fontSize.small} fill="#444">Masonry / Concrete</text>
              </g>
              <g transform={`translate(0, ${rowH * 0.7 + rowH * 2})`}>
                <rect width={swatchW} height={swatchH} fill="url(#fd-steelFill)"
                  stroke="#333" strokeWidth="0.5" />
                <text x={swatchW + fontSize.small * 0.4} y={swatchH * 0.8}
                  fontSize={fontSize.small} fill="#444">Track / Steel</text>
              </g>
              <g transform={`translate(0, ${rowH * 0.7 + rowH * 3})`}>
                <rect width={swatchW} height={swatchH} fill="#8B1A1A"
                  stroke="#333" strokeWidth="0.5" />
                <text x={swatchW + fontSize.small * 0.4} y={swatchH * 0.8}
                  fontSize={fontSize.small} fill="#444">Torsion Spring</text>
              </g>
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* NOTES                                                            */}
        {/* ================================================================ */}
        <g transform={`translate(${fontSize.label * 1.5}, ${layout.svgH - fontSize.small * 1.5})`}>
          <text fontSize={fontSize.small} fill="#888">
            All dimensions in feet-inches. Verify rough opening before installation.
            Mount type: {geo.mountType}. Track: {geo.trackSize}".
          </text>
        </g>
      </svg>
    </div>
  )
}

export default FramingDrawing
