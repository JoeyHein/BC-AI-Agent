/**
 * SideElevationDrawing Component
 * Shows side elevation view with track configuration, headroom, and backroom requirements
 */

import { useMemo } from 'react'

function SideElevationDrawing({
  width = 96,
  height = 84,
  trackRadius = 15,
  trackSize = 2,
  liftType = 'standard', // standard, low_headroom, high_lift, vertical
  highLiftInches = null,
  scale = 0.5,
  title = 'SIDE ELEVATION',
}) {
  const calculations = useMemo(() => {
    // Calculate based on lift type
    let headRoom, backRoom, horizontalTrack

    switch (liftType) {
      case 'low_headroom':
        headRoom = trackRadius === 12 ? 12 : 15
        horizontalTrack = height + 18
        backRoom = horizontalTrack + 6
        break
      case 'high_lift':
        headRoom = (highLiftInches || 48) + trackRadius
        horizontalTrack = height + 18
        backRoom = horizontalTrack + 6
        break
      case 'vertical':
        headRoom = height + 12
        horizontalTrack = 0
        backRoom = 24 // Just clearance for drums
        break
      default: // standard
        headRoom = trackRadius + 3
        horizontalTrack = height + 18
        backRoom = horizontalTrack + 6
    }

    // Derive ceiling height for drawing purposes
    const ceilingHeight = liftType === 'high_lift'
      ? height + headRoom
      : (height + headRoom + 12)

    return {
      headRoom,
      backRoom,
      horizontalTrack,
      verticalTrack: height,
      ceilingHeight,
    }
  }, [height, trackRadius, liftType, highLiftInches])

  // Drawing dimensions
  const margin = 60
  const totalHeight = calculations.ceilingHeight + 24
  const totalWidth = calculations.backRoom + 30

  const drawingWidth = totalWidth * scale + margin * 2
  const drawingHeight = totalHeight * scale + margin * 2 + 40

  const s = (inches) => inches * scale
  const originX = margin
  const originY = margin + 40 + s(calculations.ceilingHeight - height)

  const formatDim = (inches) => {
    const ft = Math.floor(inches / 12)
    const inVal = Math.round(inches % 12)
    if (ft === 0) return `${inVal}"`
    if (inVal === 0) return `${ft}'-0"`
    return `${ft}'-${inVal}"`
  }

  return (
    <div className="side-elevation-drawing bg-white border border-gray-300 rounded-lg overflow-hidden">
      <svg
        width={drawingWidth}
        height={drawingHeight}
        viewBox={`0 0 ${drawingWidth} ${drawingHeight}`}
        className="font-sans"
      >
        <defs>
          <pattern id="sideConcreteHatch" patternUnits="userSpaceOnUse" width="8" height="8">
            <path d="M0,8 L8,0" stroke="#999" strokeWidth="0.5" />
          </pattern>
          <pattern id="sideSteelFill" patternUnits="userSpaceOnUse" width="4" height="4">
            <rect width="4" height="4" fill="#B8B8B8" />
          </pattern>
          <marker id="arrowEnd" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
            <path d="M0,0 L0,6 L9,3 z" fill="#333" />
          </marker>
          <marker id="arrowStart" markerWidth="10" markerHeight="10" refX="0" refY="3" orient="auto">
            <path d="M9,0 L9,6 L0,3 z" fill="#333" />
          </marker>
        </defs>

        {/* Title */}
        <text x={drawingWidth / 2} y="20" fontSize="14" fontWeight="bold" textAnchor="middle" fill="#333">
          {title}
        </text>
        <text x={drawingWidth / 2} y="35" fontSize="10" textAnchor="middle" fill="#666">
          {liftType.replace('_', ' ').toUpperCase()} LIFT | Track: {trackSize}" | Radius: {trackRadius}"
        </text>

        {/* Main drawing */}
        <g>
          {/* Floor */}
          <line
            x1={originX - 20}
            y1={originY + s(height)}
            x2={originX + s(calculations.backRoom) + 20}
            y2={originY + s(height)}
            stroke="#333"
            strokeWidth="3"
          />
          <text x={originX - 25} y={originY + s(height) + 4} fontSize="9" fill="#666">FL</text>

          {/* Ceiling */}
          <line
            x1={originX - 20}
            y1={originY - s(calculations.headRoom)}
            x2={originX + s(calculations.backRoom) + 20}
            y2={originY - s(calculations.headRoom)}
            stroke="#333"
            strokeWidth="2"
            strokeDasharray="10,5"
          />
          <text x={originX - 25} y={originY - s(calculations.headRoom) + 4} fontSize="9" fill="#666">CL</text>

          {/* Wall/Header section */}
          <rect
            x={originX - s(6)}
            y={originY - s(calculations.headRoom + 8)}
            width={s(8)}
            height={s(calculations.headRoom + height + 20)}
            fill="url(#sideConcreteHatch)"
            stroke="#333"
            strokeWidth="1"
          />

          {/* Door opening (closed position) */}
          <rect
            x={originX}
            y={originY}
            width={s(4)}
            height={s(height)}
            fill="#0066CC"
            opacity="0.3"
            stroke="#0066CC"
            strokeWidth="1"
          />
          <text
            x={originX + s(2)}
            y={originY + s(height / 2)}
            fontSize="8"
            fill="#0066CC"
            textAnchor="middle"
            transform={`rotate(-90, ${originX + s(2)}, ${originY + s(height / 2)})`}
          >
            DOOR (CLOSED)
          </text>

          {/* Vertical track */}
          <rect
            x={originX + s(2)}
            y={originY}
            width={s(trackSize)}
            height={s(height)}
            fill="url(#sideSteelFill)"
            stroke="#333"
            strokeWidth="1"
          />

          {/* Track curve */}
          {liftType !== 'vertical' && (
            <path
              d={`M ${originX + s(2 + trackSize / 2)} ${originY}
                  A ${s(trackRadius)} ${s(trackRadius)} 0 0 0
                  ${originX + s(2 + trackSize / 2 + trackRadius)} ${originY - s(trackRadius)}`}
              fill="none"
              stroke="#333"
              strokeWidth={s(trackSize)}
              opacity="0.6"
            />
          )}

          {/* Horizontal track */}
          {calculations.horizontalTrack > 0 && (
            <rect
              x={originX + s(2 + trackRadius)}
              y={originY - s(trackRadius + trackSize / 2)}
              width={s(calculations.horizontalTrack - trackRadius)}
              height={s(trackSize)}
              fill="url(#sideSteelFill)"
              stroke="#333"
              strokeWidth="1"
            />
          )}

          {/* Door in open position (dashed) */}
          {liftType !== 'vertical' && (
            <rect
              x={originX + s(2 + trackRadius)}
              y={originY - s(trackRadius + 2)}
              width={s(height)}
              height={s(4)}
              fill="none"
              stroke="#0066CC"
              strokeWidth="1"
              strokeDasharray="5,3"
            />
          )}

          {/* Spring/shaft assembly */}
          <g className="spring-assembly">
            {/* Shaft */}
            <line
              x1={originX + s(4)}
              y1={originY - s(calculations.headRoom - 6)}
              x2={originX + s(20)}
              y2={originY - s(calculations.headRoom - 6)}
              stroke="#333"
              strokeWidth="3"
            />
            {/* Drum */}
            <circle
              cx={originX + s(12)}
              cy={originY - s(calculations.headRoom - 6)}
              r={s(4)}
              fill="#666"
              stroke="#333"
              strokeWidth="1"
            />
            {/* Cable */}
            <line
              x1={originX + s(12)}
              y1={originY - s(calculations.headRoom - 6) + s(4)}
              x2={originX + s(4)}
              y2={originY + s(height - 6)}
              stroke="#333"
              strokeWidth="1"
              strokeDasharray="3,2"
            />
          </g>

          {/* Dimension: Door Height */}
          <g className="dim-door-height">
            <line
              x1={originX + s(calculations.backRoom) + 15}
              y1={originY}
              x2={originX + s(calculations.backRoom) + 15}
              y2={originY + s(height)}
              stroke="#333"
              strokeWidth="0.5"
              markerStart="url(#arrowStart)"
              markerEnd="url(#arrowEnd)"
            />
            <text
              x={originX + s(calculations.backRoom) + 25}
              y={originY + s(height / 2)}
              fontSize="10"
              fill="#333"
              transform={`rotate(-90, ${originX + s(calculations.backRoom) + 25}, ${originY + s(height / 2)})`}
              textAnchor="middle"
            >
              {formatDim(height)}
            </text>
          </g>

          {/* Dimension: Head Room */}
          <g className="dim-headroom">
            <line
              x1={originX + s(calculations.backRoom) + 35}
              y1={originY - s(calculations.headRoom)}
              x2={originX + s(calculations.backRoom) + 35}
              y2={originY}
              stroke="#C41E3A"
              strokeWidth="0.5"
              markerStart="url(#arrowStart)"
              markerEnd="url(#arrowEnd)"
            />
            <text
              x={originX + s(calculations.backRoom) + 45}
              y={originY - s(calculations.headRoom / 2)}
              fontSize="9"
              fill="#C41E3A"
              fontWeight="bold"
              transform={`rotate(-90, ${originX + s(calculations.backRoom) + 45}, ${originY - s(calculations.headRoom / 2)})`}
              textAnchor="middle"
            >
              HEAD RM: {formatDim(calculations.headRoom)}
            </text>
          </g>

          {/* Dimension: Back Room */}
          <g className="dim-backroom">
            <line
              x1={originX}
              y1={originY - s(calculations.headRoom) - 20}
              x2={originX + s(calculations.backRoom)}
              y2={originY - s(calculations.headRoom) - 20}
              stroke="#0066CC"
              strokeWidth="0.5"
              markerStart="url(#arrowStart)"
              markerEnd="url(#arrowEnd)"
            />
            <text
              x={originX + s(calculations.backRoom / 2)}
              y={originY - s(calculations.headRoom) - 28}
              fontSize="9"
              fill="#0066CC"
              fontWeight="bold"
              textAnchor="middle"
            >
              BACK ROOM: {formatDim(calculations.backRoom)}
            </text>
          </g>

          {/* Dimension: Horizontal Track */}
          {calculations.horizontalTrack > 0 && (
            <g className="dim-horiz-track">
              <line
                x1={originX + s(2 + trackRadius)}
                y1={originY - s(trackRadius) - 10}
                x2={originX + s(2 + calculations.horizontalTrack)}
                y2={originY - s(trackRadius) - 10}
                stroke="#666"
                strokeWidth="0.5"
              />
              <text
                x={originX + s(2 + trackRadius + (calculations.horizontalTrack - trackRadius) / 2)}
                y={originY - s(trackRadius) - 15}
                fontSize="8"
                fill="#666"
                textAnchor="middle"
              >
                HORIZ. TRACK: {formatDim(calculations.horizontalTrack - trackRadius)}
              </text>
            </g>
          )}
        </g>

        {/* Requirements box */}
        <g transform={`translate(20, ${drawingHeight - 80})`}>
          <rect width="180" height="70" fill="#f5f5f5" stroke="#ccc" strokeWidth="1" rx="3" />
          <text x="10" y="15" fontSize="10" fontWeight="bold" fill="#333">CLEARANCE REQUIREMENTS:</text>
          <text x="10" y="30" fontSize="9" fill="#666">Head Room: {formatDim(calculations.headRoom)} min</text>
          <text x="10" y="43" fontSize="9" fill="#666">Back Room: {formatDim(calculations.backRoom)} min</text>
          <text x="10" y="56" fontSize="9" fill="#666">Side Room: 4" min each side</text>
        </g>
      </svg>
    </div>
  )
}

export default SideElevationDrawing
