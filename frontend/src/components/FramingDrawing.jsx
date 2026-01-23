/**
 * FramingDrawing Component
 * Generates professional construction/framing drawings for architects and contractors
 * Shows header, jamb, track, spring assembly, and hardware placement
 */

import { useMemo } from 'react'

function FramingDrawing({
  width = 96, // Door width in inches
  height = 84, // Door height in inches
  trackRadius = 15, // Track radius in inches
  trackSize = 2, // Track width (2" or 3")
  liftType = 'standard', // standard, low_headroom, high_lift, vertical
  sideRoom = 4, // Minimum side room in inches
  headRoom = null, // Head room (calculated if null)
  backRoom = null, // Back room (calculated if null)
  showSpringAssembly = true,
  showHardwareLocations = true,
  showDimensions = true,
  scale = 0.5, // Drawing scale factor
  title = 'FRAMING DRAWING',
}) {
  // Calculate dimensions
  const calculations = useMemo(() => {
    // Calculate head room based on lift type and track
    let calculatedHeadRoom = headRoom
    if (!calculatedHeadRoom) {
      switch (liftType) {
        case 'low_headroom':
          calculatedHeadRoom = trackRadius === 12 ? 12 : 15
          break
        case 'high_lift':
          calculatedHeadRoom = height + 24 // Extra for high lift
          break
        case 'vertical':
          calculatedHeadRoom = height + 48
          break
        default:
          calculatedHeadRoom = trackRadius + 3 // Standard: radius + 3"
      }
    }

    // Calculate back room (horizontal track length)
    let calculatedBackRoom = backRoom
    if (!calculatedBackRoom) {
      calculatedBackRoom = height + 18 // Door height + 18" typically
    }

    // Calculate rough opening
    const roughOpeningWidth = width + 3 // Width + 1.5" each side
    const roughOpeningHeight = height + 1.5 // Height + 1.5" header

    // Jamb dimensions
    const jambWidth = 2 // 2" jamb typically
    const jambDepth = trackSize + 1 // Track size + 1"

    // Header dimensions
    const headerHeight = 6 // 6" header beam typically
    const headerWidth = roughOpeningWidth + 12 // Extends 6" each side

    // Track dimensions
    const verticalTrackLength = height
    const horizontalTrackLength = calculatedBackRoom - trackRadius
    const curveLength = Math.PI * trackRadius / 2

    // Spring assembly position
    const springY = -calculatedHeadRoom + 6
    const shaftLength = width + 12 // Door width + drum space

    return {
      headRoom: calculatedHeadRoom,
      backRoom: calculatedBackRoom,
      roughOpeningWidth,
      roughOpeningHeight,
      jambWidth,
      jambDepth,
      headerHeight,
      headerWidth,
      verticalTrackLength,
      horizontalTrackLength,
      curveLength,
      springY,
      shaftLength,
      sideRoom,
    }
  }, [width, height, trackRadius, trackSize, liftType, headRoom, backRoom, sideRoom])

  // Drawing dimensions
  const margin = 80
  const drawingWidth = (width + calculations.sideRoom * 2 + 40) * scale + margin * 2
  const drawingHeight = (height + calculations.headRoom + 60) * scale + margin * 2

  // Helper to convert inches to scaled pixels
  const s = (inches) => inches * scale
  const originX = margin + s(calculations.sideRoom + 20)
  const originY = margin + s(calculations.headRoom + 20)

  // Dimension line helper
  const DimensionLine = ({ x1, y1, x2, y2, label, offset = 20, vertical = false }) => {
    const midX = (x1 + x2) / 2
    const midY = (y1 + y2) / 2

    if (vertical) {
      return (
        <g className="dimension-line">
          <line x1={x1 + offset} y1={y1} x2={x1 + offset} y2={y2} stroke="#333" strokeWidth="0.5" />
          <line x1={x1 + offset - 4} y1={y1} x2={x1 + offset + 4} y2={y1} stroke="#333" strokeWidth="0.5" />
          <line x1={x1 + offset - 4} y1={y2} x2={x1 + offset + 4} y2={y2} stroke="#333" strokeWidth="0.5" />
          <text
            x={x1 + offset + 5}
            y={midY}
            fontSize="10"
            fontFamily="Arial"
            transform={`rotate(-90, ${x1 + offset + 5}, ${midY})`}
            textAnchor="middle"
          >
            {label}
          </text>
        </g>
      )
    }

    return (
      <g className="dimension-line">
        <line x1={x1} y1={y1 + offset} x2={x2} y2={y1 + offset} stroke="#333" strokeWidth="0.5" />
        <line x1={x1} y1={y1 + offset - 4} x2={x1} y2={y1 + offset + 4} stroke="#333" strokeWidth="0.5" />
        <line x1={x2} y1={y1 + offset - 4} x2={x2} y2={y1 + offset + 4} stroke="#333" strokeWidth="0.5" />
        <text x={midX} y={y1 + offset + 12} fontSize="10" fontFamily="Arial" textAnchor="middle">
          {label}
        </text>
      </g>
    )
  }

  // Format dimension string
  const formatDim = (inches) => {
    const ft = Math.floor(inches / 12)
    const inVal = inches % 12
    if (ft === 0) return `${inVal}"`
    if (inVal === 0) return `${ft}'-0"`
    return `${ft}'-${inVal}"`
  }

  return (
    <div className="framing-drawing bg-white border border-gray-300 rounded-lg overflow-hidden">
      <svg
        width={drawingWidth}
        height={drawingHeight + 60}
        viewBox={`0 0 ${drawingWidth} ${drawingHeight + 60}`}
        className="font-sans"
      >
        <defs>
          {/* Hatch pattern for concrete/masonry */}
          <pattern id="concreteHatch" patternUnits="userSpaceOnUse" width="8" height="8">
            <path d="M0,8 L8,0" stroke="#999" strokeWidth="0.5" />
          </pattern>

          {/* Wood grain pattern */}
          <pattern id="woodGrain" patternUnits="userSpaceOnUse" width="20" height="4">
            <path d="M0,2 Q5,0 10,2 T20,2" stroke="#A0522D" strokeWidth="0.3" fill="none" />
          </pattern>

          {/* Steel fill */}
          <pattern id="steelFill" patternUnits="userSpaceOnUse" width="4" height="4">
            <rect width="4" height="4" fill="#B8B8B8" />
            <circle cx="2" cy="2" r="0.5" fill="#999" />
          </pattern>
        </defs>

        {/* Title block */}
        <g transform={`translate(${drawingWidth / 2}, 25)`}>
          <text fontSize="16" fontWeight="bold" textAnchor="middle" fill="#333">
            {title}
          </text>
          <text fontSize="11" textAnchor="middle" y="18" fill="#666">
            Door Size: {formatDim(width)} W x {formatDim(height)} H | Track: {trackSize}" | Radius: {trackRadius}"
          </text>
        </g>

        {/* Main drawing group */}
        <g transform={`translate(0, 40)`}>
          {/* Floor line */}
          <line
            x1={originX - s(20)}
            y1={originY + s(height)}
            x2={originX + s(width + 20)}
            y2={originY + s(height)}
            stroke="#333"
            strokeWidth="2"
          />
          <text
            x={originX - s(25)}
            y={originY + s(height) + 4}
            fontSize="9"
            fill="#666"
          >
            FLOOR
          </text>

          {/* Left wall/jamb */}
          <g className="left-jamb">
            <rect
              x={originX - s(calculations.jambWidth)}
              y={originY - s(calculations.headRoom)}
              width={s(calculations.jambWidth)}
              height={s(height + calculations.headRoom)}
              fill="url(#woodGrain)"
              stroke="#333"
              strokeWidth="1"
            />
            <rect
              x={originX - s(calculations.jambWidth + 8)}
              y={originY - s(calculations.headRoom)}
              width={s(8)}
              height={s(height + calculations.headRoom + 12)}
              fill="url(#concreteHatch)"
              stroke="#333"
              strokeWidth="1"
            />
          </g>

          {/* Right wall/jamb */}
          <g className="right-jamb">
            <rect
              x={originX + s(width)}
              y={originY - s(calculations.headRoom)}
              width={s(calculations.jambWidth)}
              height={s(height + calculations.headRoom)}
              fill="url(#woodGrain)"
              stroke="#333"
              strokeWidth="1"
            />
            <rect
              x={originX + s(width + calculations.jambWidth)}
              y={originY - s(calculations.headRoom)}
              width={s(8)}
              height={s(height + calculations.headRoom + 12)}
              fill="url(#concreteHatch)"
              stroke="#333"
              strokeWidth="1"
            />
          </g>

          {/* Header */}
          <g className="header">
            <rect
              x={originX - s(6)}
              y={originY - s(calculations.headRoom + calculations.headerHeight)}
              width={s(width + 12)}
              height={s(calculations.headerHeight)}
              fill="url(#woodGrain)"
              stroke="#333"
              strokeWidth="1.5"
            />
            <text
              x={originX + s(width / 2)}
              y={originY - s(calculations.headRoom + calculations.headerHeight / 2) + 4}
              fontSize="10"
              textAnchor="middle"
              fill="#333"
            >
              HEADER
            </text>
          </g>

          {/* Left vertical track */}
          <g className="left-track">
            <rect
              x={originX + s(1)}
              y={originY}
              width={s(trackSize)}
              height={s(height)}
              fill="url(#steelFill)"
              stroke="#333"
              strokeWidth="1"
            />
            {/* Track mounting flags */}
            {[0, height * 0.33, height * 0.66, height - 6].map((y, i) => (
              <rect
                key={`lf-${i}`}
                x={originX - s(1)}
                y={originY + s(y)}
                width={s(trackSize + 3)}
                height={s(4)}
                fill="#666"
                stroke="#333"
                strokeWidth="0.5"
              />
            ))}
          </g>

          {/* Right vertical track */}
          <g className="right-track">
            <rect
              x={originX + s(width - trackSize - 1)}
              y={originY}
              width={s(trackSize)}
              height={s(height)}
              fill="url(#steelFill)"
              stroke="#333"
              strokeWidth="1"
            />
            {/* Track mounting flags */}
            {[0, height * 0.33, height * 0.66, height - 6].map((y, i) => (
              <rect
                key={`rf-${i}`}
                x={originX + s(width - 2)}
                y={originY + s(y)}
                width={s(trackSize + 3)}
                height={s(4)}
                fill="#666"
                stroke="#333"
                strokeWidth="0.5"
              />
            ))}
          </g>

          {/* Track curves (radius) */}
          <g className="track-curves">
            {/* Left curve */}
            <path
              d={`M ${originX + s(1 + trackSize / 2)} ${originY}
                  A ${s(trackRadius)} ${s(trackRadius)} 0 0 1
                  ${originX + s(1 + trackSize / 2 + trackRadius)} ${originY - s(trackRadius)}`}
              fill="none"
              stroke="#333"
              strokeWidth={s(trackSize)}
              opacity="0.3"
            />
            {/* Right curve */}
            <path
              d={`M ${originX + s(width - 1 - trackSize / 2)} ${originY}
                  A ${s(trackRadius)} ${s(trackRadius)} 0 0 0
                  ${originX + s(width - 1 - trackSize / 2 - trackRadius)} ${originY - s(trackRadius)}`}
              fill="none"
              stroke="#333"
              strokeWidth={s(trackSize)}
              opacity="0.3"
            />
          </g>

          {/* Horizontal tracks (shown as dashed for depth indication) */}
          <g className="horizontal-tracks">
            <line
              x1={originX + s(1 + trackSize / 2 + trackRadius)}
              y1={originY - s(trackRadius)}
              x2={originX + s(1 + trackSize / 2 + trackRadius) + s(calculations.backRoom - trackRadius - 20)}
              y2={originY - s(trackRadius)}
              stroke="#333"
              strokeWidth={s(trackSize)}
              strokeDasharray="10,5"
              opacity="0.3"
            />
          </g>

          {/* Spring assembly */}
          {showSpringAssembly && (
            <g className="spring-assembly">
              {/* Torsion shaft */}
              <line
                x1={originX + s(2)}
                y1={originY - s(calculations.headRoom - 8)}
                x2={originX + s(width - 2)}
                y2={originY - s(calculations.headRoom - 8)}
                stroke="#333"
                strokeWidth="3"
              />

              {/* Left drum */}
              <circle
                cx={originX + s(6)}
                cy={originY - s(calculations.headRoom - 8)}
                r={s(4)}
                fill="#666"
                stroke="#333"
                strokeWidth="1"
              />

              {/* Right drum */}
              <circle
                cx={originX + s(width - 6)}
                cy={originY - s(calculations.headRoom - 8)}
                r={s(4)}
                fill="#666"
                stroke="#333"
                strokeWidth="1"
              />

              {/* Springs (simplified as rectangles) */}
              <rect
                x={originX + s(width / 2 - 20)}
                y={originY - s(calculations.headRoom - 6)}
                width={s(18)}
                height={s(4)}
                fill="#C41E3A"
                stroke="#333"
                strokeWidth="0.5"
                rx="2"
              />
              <rect
                x={originX + s(width / 2 + 2)}
                y={originY - s(calculations.headRoom - 6)}
                width={s(18)}
                height={s(4)}
                fill="#C41E3A"
                stroke="#333"
                strokeWidth="0.5"
                rx="2"
              />

              {/* Center bearing plate */}
              <rect
                x={originX + s(width / 2 - 3)}
                y={originY - s(calculations.headRoom - 3)}
                width={s(6)}
                height={s(10)}
                fill="#444"
                stroke="#333"
                strokeWidth="1"
              />

              <text
                x={originX + s(width / 2)}
                y={originY - s(calculations.headRoom - 18)}
                fontSize="8"
                textAnchor="middle"
                fill="#666"
              >
                SPRING ASSEMBLY
              </text>
            </g>
          )}

          {/* Door outline (dashed to show opening) */}
          <rect
            x={originX}
            y={originY}
            width={s(width)}
            height={s(height)}
            fill="none"
            stroke="#0066CC"
            strokeWidth="1.5"
            strokeDasharray="8,4"
          />

          {/* Hardware locations */}
          {showHardwareLocations && (
            <g className="hardware-locations">
              {/* Bottom brackets */}
              <rect
                x={originX + s(3)}
                y={originY + s(height - 8)}
                width={s(8)}
                height={s(6)}
                fill="#FF6B35"
                stroke="#333"
                strokeWidth="0.5"
              />
              <rect
                x={originX + s(width - 11)}
                y={originY + s(height - 8)}
                width={s(8)}
                height={s(6)}
                fill="#FF6B35"
                stroke="#333"
                strokeWidth="0.5"
              />

              {/* Top brackets */}
              <rect
                x={originX + s(3)}
                y={originY + s(2)}
                width={s(8)}
                height={s(6)}
                fill="#FF6B35"
                stroke="#333"
                strokeWidth="0.5"
              />
              <rect
                x={originX + s(width - 11)}
                y={originY + s(2)}
                width={s(8)}
                height={s(6)}
                fill="#FF6B35"
                stroke="#333"
                strokeWidth="0.5"
              />
            </g>
          )}

          {/* Dimensions */}
          {showDimensions && (
            <g className="dimensions">
              {/* Door width */}
              <DimensionLine
                x1={originX}
                y1={originY + s(height)}
                x2={originX + s(width)}
                y2={originY + s(height)}
                label={formatDim(width)}
                offset={25}
              />

              {/* Door height */}
              <DimensionLine
                x1={originX + s(width)}
                y1={originY}
                x2={originX + s(width)}
                y2={originY + s(height)}
                label={formatDim(height)}
                offset={s(calculations.sideRoom) + 15}
                vertical
              />

              {/* Head room */}
              <DimensionLine
                x1={originX}
                y1={originY - s(calculations.headRoom)}
                x2={originX}
                y2={originY}
                label={`HEAD ROOM: ${formatDim(calculations.headRoom)}`}
                offset={-40}
                vertical
              />

              {/* Side room */}
              <g>
                <text
                  x={originX - s(calculations.jambWidth + 4)}
                  y={originY + s(height / 2)}
                  fontSize="9"
                  fill="#666"
                  textAnchor="end"
                  transform={`rotate(-90, ${originX - s(calculations.jambWidth + 4)}, ${originY + s(height / 2)})`}
                >
                  SIDE ROOM: {formatDim(calculations.sideRoom)} MIN
                </text>
              </g>

              {/* Rough opening */}
              <text
                x={originX + s(width / 2)}
                y={originY - s(calculations.headRoom + calculations.headerHeight + 8)}
                fontSize="10"
                fontWeight="bold"
                textAnchor="middle"
                fill="#333"
              >
                R.O. {formatDim(calculations.roughOpeningWidth)} x {formatDim(calculations.roughOpeningHeight)}
              </text>
            </g>
          )}
        </g>

        {/* Legend */}
        <g transform={`translate(${drawingWidth - 140}, ${drawingHeight - 20})`}>
          <text fontSize="9" fontWeight="bold" fill="#333">LEGEND:</text>
          <g transform="translate(0, 12)">
            <rect width="15" height="8" fill="url(#woodGrain)" stroke="#333" strokeWidth="0.5" />
            <text x="20" y="7" fontSize="8">Wood Framing</text>
          </g>
          <g transform="translate(0, 24)">
            <rect width="15" height="8" fill="url(#concreteHatch)" stroke="#333" strokeWidth="0.5" />
            <text x="20" y="7" fontSize="8">Masonry/Concrete</text>
          </g>
          <g transform="translate(0, 36)">
            <rect width="15" height="8" fill="url(#steelFill)" stroke="#333" strokeWidth="0.5" />
            <text x="20" y="7" fontSize="8">Track/Steel</text>
          </g>
          <g transform="translate(0, 48)">
            <rect width="15" height="8" fill="#FF6B35" stroke="#333" strokeWidth="0.5" />
            <text x="20" y="7" fontSize="8">Hardware</text>
          </g>
        </g>

        {/* Notes section */}
        <g transform={`translate(20, ${drawingHeight + 5})`}>
          <text fontSize="9" fontWeight="bold" fill="#333">NOTES:</text>
          <text fontSize="8" y="12" fill="#666">
            1. All dimensions in feet-inches unless noted otherwise.
          </text>
          <text fontSize="8" y="22" fill="#666">
            2. Verify rough opening dimensions before installation.
          </text>
          <text fontSize="8" y="32" fill="#666">
            3. Header must support door weight plus spring tension.
          </text>
        </g>
      </svg>
    </div>
  )
}

export default FramingDrawing
