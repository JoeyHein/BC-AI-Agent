/**
 * FramingDrawing Component
 * Professional Thermalex-style shop drawing showing interior face view
 * ("DOOR FACE: INSIDE LOOKING OUT") for garage door installation.
 *
 * Modeled after actual Thermalex Panorama / Craft / TX-450 sample drawings:
 * - Black line art on white (no colored fills)
 * - Monospace technical font (Courier New)
 * - 45-degree diagonal tick marks on dimension lines
 * - Professional title block, optional extras list, jamb detail
 *
 * Receives a `geometry` prop from the backend with exact Thermalex dimensions.
 *
 * ALL visual sizes (fonts, ticks, margins, offsets) are proportional to the
 * drawing size via a `baseUnit` derived from door dimensions and scale, so
 * labels never overlap even on large doors (e.g. 16x16).
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
  // Resolve geometry
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
      doorWidth: dw, doorHeight: dh, frameType: ft, frameWidth: fw,
      sideroom: sr, sideroomAngle: srAngle, sideroomBracket: srBracket,
      centerPost: cp, ust, clShaft, headroomMin: hrMin, backroom: br,
      verticalTrackLength: vtl, horizontalTrackLength: htl,
      trackRadius: tr, trackSize: ts, liftType: lt, mountType: mt,
      trackTypeLabel: ttl, radiusLabel: rl,
    }
  }, [geometry, width, height, trackRadius, trackSize, liftType, frameType, mountType])

  // ---------------------------------------------------------------------------
  // Fixed page size: 11" x 8.5" landscape at 96 DPI = 1056 x 816
  // All content scales to fit within this page.
  // ---------------------------------------------------------------------------
  const PAGE_W = 1056
  const PAGE_H = 816

  const ui = useMemo(() => {
    const doorW = geo.doorWidth
    const doorH = geo.doorHeight

    // Compute scale to fit door + margins within the fixed page
    const wallThickness = 6
    const fw = geo.frameWidth
    const sr = geo.sideroom
    const clShaft = geo.clShaft
    const hrMin = geo.headroomMin
    const headerHeight = 4

    // Content extents in inches
    const contentWInches = doorW + (fw + wallThickness + sr) * 2 + 40 // extra for dims + right panel
    const topClearanceInches = Math.max(hrMin, clShaft) + headerHeight + 10
    const contentHInches = topClearanceInches + doorH + 30 // extra for bottom dims + jamb detail

    // Auto-scale: fit content into ~85% of page (leave room for title block, extras)
    const usableW = PAGE_W * 0.6  // left ~60% for the drawing
    const usableH = PAGE_H * 0.85
    const autoScale = Math.min(usableW / contentWInches, usableH / contentHInches)

    const baseUnit = Math.max(5, Math.min(10, Math.sqrt(Math.max(doorW, doorH) * autoScale) * 0.7))

    const fontSize = {
      title: baseUnit * 1.6,
      subtitle: baseUnit * 1.2,
      label: baseUnit * 1.0,
      small: baseUnit * 0.8,
      tiny: baseUnit * 0.6,
    }
    const tickLen = baseUnit * 0.55
    const dimLineSpacing = baseUnit * 3
    const margin = {
      top: Math.max(50, baseUnit * 6),
      right: Math.max(200, baseUnit * 24),
      bottom: Math.max(80, baseUnit * 10),
      left: Math.max(70, baseUnit * 9),
    }
    const leaderLen = baseUnit * 2.5
    const calloutScale = Math.max(1.5, baseUnit * 0.3)

    return { baseUnit, fontSize, tickLen, dimLineSpacing, margin, leaderLen, calloutScale, autoScale }
  }, [geo])

  // ---------------------------------------------------------------------------
  // Derived layout values — everything fits within the fixed PAGE_W x PAGE_H
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
    const wallThickness = 6
    const headerHeight = 4
    const topClearance = Math.max(hrMin, shaftY) + headerHeight + 8

    const { margin, dimLineSpacing, autoScale } = ui

    const minTopPx = 80
    const topClearancePx = Math.max(minTopPx, topClearance * autoScale)

    const contentW = dw + (fw + wallThickness + sr) * 2

    const svgW = PAGE_W
    const svgH = PAGE_H

    const originX = margin.left + (fw + wallThickness + sr) * autoScale
    const originY = margin.top + topClearancePx

    return {
      dw, dh, fw, sr, hrMin, clShaft, ts, tr,
      shaftY, wallThickness, headerHeight, topClearance, topClearancePx,
      margin, contentW, svgW, svgH,
      originX, originY, dimLineSpacing,
    }
  }, [geo, ui])

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  const s = (inches) => inches * ui.autoScale

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
  const applicationLabel = isSteel ? 'STEEL JAMB RESI APPLICATION' : 'WOOD JAMB APPLICATION'

  const { fontSize, tickLen, dimLineSpacing, calloutScale } = ui

  // Track flag positions (evenly along vertical track)
  const flagCount = 5
  const flagPositions = Array.from({ length: flagCount }, (_, i) =>
    (i / (flagCount - 1)) * (dh - 6) + 3
  )

  // Panel positions (horizontal lines inside door opening representing panels)
  const panelCount = doorType === 'commercial' ? Math.max(3, Math.round(dh / 24)) : Math.max(3, Math.round(dh / 21))
  const panelHeight = dh / panelCount

  // Shaft position
  const shaftYPx = oy - s(layout.clShaft)

  // 45-degree diagonal tick helper: draws a short slash rotated 45 degrees
  const DiagTick = ({ x, y, len = tickLen, stroke = '#000', strokeWidth = 0.8 }) => {
    const half = len / 2
    // 45-degree slash: from bottom-left to top-right
    return (
      <line
        x1={x - half * 0.707} y1={y + half * 0.707}
        x2={x + half * 0.707} y2={y - half * 0.707}
        stroke={stroke} strokeWidth={strokeWidth}
      />
    )
  }

  // Right panel area start X
  const rightPanelX = ox + s(dw + fw + layout.wallThickness) + dimLineSpacing * 2.5 + fontSize.label * 3

  // Optional extras list
  const optionalExtras = [
    `${ts}" TRACK APPLICATION`,
    isSteel ? 'STEEL FRAME' : 'WOOD FRAME',
    geo.mountType === 'bracket' ? 'BRACKET MOUNT' : 'CONTINUOUS ANGLE MOUNT',
    'SINGLE END STILE/HINGE',
    'DOUBLE END STILE/HINGE',
    '20GA STRUTS',
    'DOOR STRUTS (EXTRA)',
    'DOUBLE LIFE SPRING',
    'KEYED SIDE LOCK',
    'DECORATIVE HARDWARE',
    'ELECTRIC OPERATOR',
    '1" TUBULAR SHAFT',
    '11,000 / 50,000 CYCLE SPRING',
    'TOP SEAL VINYL',
    'RUBBER ASTRAGAL',
  ]

  return (
    <div className="framing-drawing bg-white border border-gray-300 rounded-lg overflow-hidden">
      <svg
        viewBox={`0 0 ${PAGE_W} ${PAGE_H}`}
        style={{
          fontFamily: "'Courier New', Courier, monospace",
          width: '100%',
          aspectRatio: '11 / 8.5',
        }}
      >
        <defs>
          {/* Diagonal hatch for wall/masonry sections */}
          <pattern id="fd-hatch" patternUnits="userSpaceOnUse" width="6" height="6"
            patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="#000" strokeWidth="0.4" />
          </pattern>

          {/* Cross-hatch for steel jambs */}
          <pattern id="fd-steelHatch" patternUnits="userSpaceOnUse" width="6" height="6">
            <line x1="0" y1="0" x2="6" y2="6" stroke="#000" strokeWidth="0.3" />
            <line x1="6" y1="0" x2="0" y2="6" stroke="#000" strokeWidth="0.3" />
          </pattern>

          {/* Wood grain hatch */}
          <pattern id="fd-woodHatch" patternUnits="userSpaceOnUse" width="12" height="6">
            <path d="M0,3 Q3,1 6,3 T12,3" stroke="#000" strokeWidth="0.3" fill="none" />
          </pattern>
        </defs>

        {/* ================================================================ */}
        {/* TOP LABEL: DOOR FACE: INSIDE LOOKING OUT                        */}
        {/* ================================================================ */}
        <text x={ox + s(dw / 2)} y={fontSize.title + 6} fontSize={fontSize.title}
          fontWeight="bold" textAnchor="middle" fill="#000">
          DOOR FACE: INSIDE LOOKING OUT
        </text>

        {/* ================================================================ */}
        {/* 3" FRAME CALLOUT AT TOP                                         */}
        {/* ================================================================ */}
        {(() => {
          const frameTopY = oy - s(layout.topClearance - layout.headerHeight - 2)
          const calloutY = frameTopY - fontSize.label * 2.5
          // Left frame callout
          const lfx1 = ox - s(fw)
          const lfx2 = ox
          // Right frame callout
          const rfx1 = ox + s(dw)
          const rfx2 = ox + s(dw + fw)
          return (
            <g className="frame-callouts">
              {/* Left */}
              <line x1={lfx1} y1={calloutY} x2={lfx2} y2={calloutY} stroke="#000" strokeWidth="0.5" />
              <DiagTick x={lfx1} y={calloutY} />
              <DiagTick x={lfx2} y={calloutY} />
              <line x1={lfx1} y1={calloutY - tickLen} x2={lfx1} y2={frameTopY} stroke="#000" strokeWidth="0.3" />
              <line x1={lfx2} y1={calloutY - tickLen} x2={lfx2} y2={frameTopY} stroke="#000" strokeWidth="0.3" />
              <text x={(lfx1 + lfx2) / 2} y={calloutY - fontSize.tiny * 0.8}
                fontSize={fontSize.tiny} textAnchor="middle" fill="#000">
                {formatDim(fw)} FRAME
              </text>
              {/* Right */}
              <line x1={rfx1} y1={calloutY} x2={rfx2} y2={calloutY} stroke="#000" strokeWidth="0.5" />
              <DiagTick x={rfx1} y={calloutY} />
              <DiagTick x={rfx2} y={calloutY} />
              <line x1={rfx1} y1={calloutY - tickLen} x2={rfx1} y2={frameTopY} stroke="#000" strokeWidth="0.3" />
              <line x1={rfx2} y1={calloutY - tickLen} x2={rfx2} y2={frameTopY} stroke="#000" strokeWidth="0.3" />
              <text x={(rfx1 + rfx2) / 2} y={calloutY - fontSize.tiny * 0.8}
                fontSize={fontSize.tiny} textAnchor="middle" fill="#000">
                {formatDim(fw)} FRAME
              </text>
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* FLOOR LINE                                                      */}
        {/* ================================================================ */}
        <line
          x1={ox - s(fw + layout.wallThickness + 12)}
          y1={oy + s(dh)}
          x2={ox + s(dw + fw + layout.wallThickness + 12)}
          y2={oy + s(dh)}
          stroke="#000" strokeWidth="2"
        />
        {/* Floor hatch below line */}
        {Array.from({ length: Math.ceil((dw + 2 * (fw + layout.wallThickness + 12)) / 4) }, (_, i) => {
          const lx = ox - s(fw + layout.wallThickness + 12) + i * s(4)
          const ly = oy + s(dh)
          return (
            <line key={`fh-${i}`} x1={lx} y1={ly + 1} x2={lx + s(2.5)} y2={ly + s(2.5)}
              stroke="#000" strokeWidth="0.4" />
          )
        })}

        {/* ================================================================ */}
        {/* WALL SECTIONS (hatched) — extend from above everything to floor */}
        {/* ================================================================ */}
        {/* Left wall */}
        <rect
          x={ox - s(fw + layout.wallThickness)}
          y={oy - s(layout.topClearance - 2)}
          width={s(layout.wallThickness)}
          height={s(dh + layout.topClearance - 2 + 6)}
          fill="url(#fd-hatch)" stroke="#000" strokeWidth="1"
        />
        {/* Right wall */}
        <rect
          x={ox + s(dw + fw)}
          y={oy - s(layout.topClearance - 2)}
          width={s(layout.wallThickness)}
          height={s(dh + layout.topClearance - 2 + 6)}
          fill="url(#fd-hatch)" stroke="#000" strokeWidth="1"
        />

        {/* ================================================================ */}
        {/* JAMBS — extend from header down to floor                       */}
        {/* ================================================================ */}
        {/* Left jamb */}
        <rect
          x={ox - s(fw)}
          y={oy - s(layout.headerHeight)}
          width={s(fw)}
          height={s(dh + layout.headerHeight)}
          fill={isSteel ? 'url(#fd-steelHatch)' : 'url(#fd-woodHatch)'}
          stroke="#000" strokeWidth="1"
        />
        {/* Right jamb */}
        <rect
          x={ox + s(dw)}
          y={oy - s(layout.headerHeight)}
          width={s(fw)}
          height={s(dh + layout.headerHeight)}
          fill={isSteel ? 'url(#fd-steelHatch)' : 'url(#fd-woodHatch)'}
          stroke="#000" strokeWidth="1"
        />

        {/* ================================================================ */}
        {/* HEADER — structural beam just ABOVE the door opening           */}
        {/* Springs/shaft sit ABOVE this header                            */}
        {/* ================================================================ */}
        {(() => {
          const headerH = Math.max(8, s(layout.headerHeight))
          return (
            <rect
              x={ox - s(fw + 2)}
              y={oy - headerH}
              width={s(dw + fw * 2 + 4)}
              height={headerH}
              fill={isSteel ? 'url(#fd-steelHatch)' : 'url(#fd-woodHatch)'}
              stroke="#000" strokeWidth="1.5"
            />
          )
        })()}

        {/* ================================================================ */}
        {/* DOOR PANELS (visible inside opening)                            */}
        {/* ================================================================ */}
        {/* Door opening outline - solid black, thick */}
        <rect
          x={ox} y={oy}
          width={s(dw)} height={s(dh)}
          fill="none" stroke="#000" strokeWidth="1.5"
        />
        {(() => {
          // Track inset in pixels — used to offset panel lines from tracks
          const tInset = Math.max(8, s(ts + 3))
          return (
            <g className="door-panels">
              {/* Panel divider lines */}
              {Array.from({ length: panelCount - 1 }, (_, i) => {
                const py = oy + s(panelHeight * (i + 1))
                return (
                  <line key={`panel-${i}`}
                    x1={ox + tInset} y1={py}
                    x2={ox + s(dw) - tInset} y2={py}
                    stroke="#000" strokeWidth="0.6"
                  />
                )
              })}
              {/* Panel ribbing/texture lines */}
              {doorType === 'commercial' ? (
                Array.from({ length: panelCount }, (_, pi) => {
                  const ribCount = 3
                  return Array.from({ length: ribCount }, (_, ri) => {
                    const py = oy + s(panelHeight * pi + panelHeight * (ri + 1) / (ribCount + 1))
                    return (
                      <line key={`rib-${pi}-${ri}`}
                        x1={ox + tInset + 2} y1={py}
                        x2={ox + s(dw) - tInset - 2} y2={py}
                        stroke="#000" strokeWidth="0.2" opacity="0.4"
                      />
                    )
                  })
                })
              ) : (
                Array.from({ length: panelCount }, (_, pi) => {
                  const panelTop = oy + s(panelHeight * pi) + 3
                  const panelBot = oy + s(panelHeight * (pi + 1)) - 3
                  const panelLeft = ox + tInset + 3
                  const panelRight = ox + s(dw) - tInset - 3
                  const midX = ox + s(dw) / 2
                  return (
                    <g key={`rpanel-${pi}`}>
                      <rect x={panelLeft} y={panelTop} width={midX - panelLeft - 2} height={panelBot - panelTop}
                        fill="none" stroke="#000" strokeWidth="0.3" opacity="0.35" />
                      <rect x={midX + 2} y={panelTop} width={panelRight - midX - 2} height={panelBot - panelTop}
                        fill="none" stroke="#000" strokeWidth="0.3" opacity="0.35" />
                    </g>
                  )
                })
              )}
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* VERTICAL TRACKS — drawn AFTER panels so they render on top     */}
        {/* ================================================================ */}
        {(() => {
          const trackW = Math.max(6, s(ts))
          const trackInset = Math.max(4, s(1.5))
          const doorPxW = s(dw)
          const trackH = s(geo.verticalTrackLength)
          return (
            <g className="vertical-tracks">
              {/* Left track — filled white rect with black outline */}
              <rect x={ox + trackInset} y={oy} width={trackW} height={trackH}
                fill="#fff" stroke="#000" strokeWidth="1.5" />
              {/* Right track */}
              <rect x={ox + doorPxW - trackInset - trackW} y={oy} width={trackW} height={trackH}
                fill="#fff" stroke="#000" strokeWidth="1.5" />

              {/* Track mounting angle flags — L-shaped brackets */}
              {flagPositions.map((yPos, i) => {
                const fy = oy + s(yPos)
                const flagW = Math.max(10, s(5))
                const flagH = Math.max(8, s(4))
                return (
                  <g key={`flags-${i}`}>
                    {/* Left flag — L bracket pointing left */}
                    <path
                      d={`M ${ox + trackInset} ${fy}
                          L ${ox + trackInset - flagW} ${fy}
                          L ${ox + trackInset - flagW} ${fy + flagH}`}
                      fill="none" stroke="#000" strokeWidth="1.2"
                    />
                    {/* Right flag — L bracket pointing right */}
                    <path
                      d={`M ${ox + doorPxW - trackInset} ${fy}
                          L ${ox + doorPxW - trackInset + flagW} ${fy}
                          L ${ox + doorPxW - trackInset + flagW} ${fy + flagH}`}
                      fill="none" stroke="#000" strokeWidth="1.2"
                    />
                  </g>
                )
              })}
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* TRACK CURVES + HORIZONTAL TRACKS                               */}
        {/* ================================================================ */}
        {(() => {
          const trackInset = Math.max(4, s(1.5))
          const trackW = Math.max(6, s(ts))
          const doorPxW = s(dw)
          const curveR = Math.max(15, s(tr))
          // Left curve start: center of left track
          const lcx = ox + trackInset + trackW / 2
          const rcx = ox + doorPxW - trackInset - trackW / 2
          return (
            <g className="track-curves">
              {/* Left — thick arc representing track curve */}
              <path d={`M ${lcx} ${oy} A ${curveR} ${curveR} 0 0 1 ${lcx + curveR} ${oy - curveR}`}
                fill="none" stroke="#000" strokeWidth={Math.max(trackW * 0.8, 3)} />
              {/* Right */}
              <path d={`M ${rcx} ${oy} A ${curveR} ${curveR} 0 0 0 ${rcx - curveR} ${oy - curveR}`}
                fill="none" stroke="#000" strokeWidth={Math.max(trackW * 0.8, 3)} />

              {/* Horizontal tracks (dashed, receding into building) */}
              <line x1={lcx + curveR} y1={oy - curveR}
                x2={lcx + curveR + Math.max(50, s(36))} y2={oy - curveR}
                stroke="#000" strokeWidth="1.5" strokeDasharray="8,4" />
              <line x1={rcx - curveR} y1={oy - curveR}
                x2={rcx - curveR - Math.max(50, s(36))} y2={oy - curveR}
                stroke="#000" strokeWidth="1.5" strokeDasharray="8,4" />
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* SPRING ASSEMBLY                                                */}
        {/* All sizes use minimum pixel values to stay visible             */}
        {/* ================================================================ */}
        {(() => {
          const doorPxW = s(dw)
          const midX = ox + doorPxW / 2
          // Drum radius: proportional but with minimum
          const drumR = Math.max(8, s(4.5))
          // Spring dimensions
          const springW = Math.max(60, doorPxW * 0.18)
          const springH = Math.max(12, s(5))
          // Center bearing plate
          const cbpW = Math.max(8, s(4))
          const cbpH = Math.max(18, springH * 1.5)
          // Drum positions: inset from track curves
          const drumLX = ox + Math.max(20, s(8))
          const drumRX = ox + doorPxW - Math.max(20, s(8))
          // Spring positions: between drums and center
          const springGap = cbpW / 2 + 2
          const springLX = midX - springGap - springW
          const springRX = midX + springGap

          return (
            <g className="spring-assembly">
              {/* Torsion shaft — bold line */}
              <line
                x1={drumLX - drumR - 4} y1={shaftYPx}
                x2={drumRX + drumR + 4} y2={shaftYPx}
                stroke="#000" strokeWidth="2.5"
              />

              {/* Left cable drum — side-view ellipse (wider along shaft) with X */}
              {(() => {
                const rx = drumR * 1.4  // wider along shaft (horizontal)
                const ry = drumR * 0.7  // narrower vertically (side view)
                return (
                  <g>
                    <ellipse cx={drumLX} cy={shaftYPx} rx={rx} ry={ry}
                      fill="#fff" stroke="#000" strokeWidth="1.5" />
                    <line x1={drumLX - rx * 0.6} y1={shaftYPx - ry * 0.6}
                      x2={drumLX + rx * 0.6} y2={shaftYPx + ry * 0.6}
                      stroke="#000" strokeWidth="0.8" />
                    <line x1={drumLX - rx * 0.6} y1={shaftYPx + ry * 0.6}
                      x2={drumLX + rx * 0.6} y2={shaftYPx - ry * 0.6}
                      stroke="#000" strokeWidth="0.8" />
                  </g>
                )
              })()}

              {/* Right cable drum — side-view ellipse with X */}
              {(() => {
                const rx = drumR * 1.4
                const ry = drumR * 0.7
                return (
                  <g>
                    <ellipse cx={drumRX} cy={shaftYPx} rx={rx} ry={ry}
                      fill="#fff" stroke="#000" strokeWidth="1.5" />
                    <line x1={drumRX - rx * 0.6} y1={shaftYPx - ry * 0.6}
                      x2={drumRX + rx * 0.6} y2={shaftYPx + ry * 0.6}
                      stroke="#000" strokeWidth="0.8" />
                    <line x1={drumRX - rx * 0.6} y1={shaftYPx + ry * 0.6}
                      x2={drumRX + rx * 0.6} y2={shaftYPx - ry * 0.6}
                      stroke="#000" strokeWidth="0.8" />
                  </g>
                )
              })()}

              {/* Left spring — rectangle with coil lines */}
              <rect x={springLX} y={shaftYPx - springH / 2}
                width={springW} height={springH}
                fill="none" stroke="#000" strokeWidth="1" />
              {Array.from({ length: Math.max(6, Math.round(springW / 6)) }, (_, i) => {
                const lx = springLX + (springW / (Math.max(6, Math.round(springW / 6)) + 1)) * (i + 1)
                return (
                  <line key={`scl-${i}`}
                    x1={lx} y1={shaftYPx - springH / 2}
                    x2={lx} y2={shaftYPx + springH / 2}
                    stroke="#000" strokeWidth="0.4" />
                )
              })}

              {/* Right spring — rectangle with coil lines */}
              <rect x={springRX} y={shaftYPx - springH / 2}
                width={springW} height={springH}
                fill="none" stroke="#000" strokeWidth="1" />
              {Array.from({ length: Math.max(6, Math.round(springW / 6)) }, (_, i) => {
                const lx = springRX + (springW / (Math.max(6, Math.round(springW / 6)) + 1)) * (i + 1)
                return (
                  <line key={`scr-${i}`}
                    x1={lx} y1={shaftYPx - springH / 2}
                    x2={lx} y2={shaftYPx + springH / 2}
                    stroke="#000" strokeWidth="0.4" />
                )
              })}

              {/* Center bearing plate — rectangle with mount bracket */}
              <rect x={midX - cbpW / 2} y={shaftYPx - cbpH / 2}
                width={cbpW} height={cbpH}
                fill="#fff" stroke="#000" strokeWidth="1.2" />
              {/* Mount angle at top of bearing plate */}
              <line x1={midX - cbpW / 2 - 3} y1={shaftYPx - cbpH / 2}
                x2={midX + cbpW / 2 + 3} y2={shaftYPx - cbpH / 2}
                stroke="#000" strokeWidth="1.5" />
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* CENTERLINE OF SHAFT label                                       */}
        {/* ================================================================ */}
        <g>
          <line
            x1={layout.margin.left * 0.2} y1={shaftYPx}
            x2={ox - s(fw + layout.wallThickness + 2)} y2={shaftYPx}
            stroke="#000" strokeWidth="0.4" strokeDasharray="4,2"
          />
          <text
            x={layout.margin.left * 0.15}
            y={shaftYPx - fontSize.small * 0.6}
            fontSize={fontSize.small} fill="#000" textAnchor="start" fontWeight="bold"
          >
            CENTRELINE
          </text>
          <text
            x={layout.margin.left * 0.15}
            y={shaftYPx + fontSize.small * 0.6}
            fontSize={fontSize.small} fill="#000" textAnchor="start" fontWeight="bold"
          >
            OF SHAFT
          </text>
        </g>

        {/* ================================================================ */}
        {/* DIMENSION LINES (with 45-degree diagonal tick marks)            */}
        {/* ================================================================ */}

        {/* --- Door Width / Opening (below floor line) --- */}
        {(() => {
          const dimY = oy + s(dh) + dimLineSpacing * 0.8
          const x1 = ox
          const x2 = ox + s(dw)
          return (
            <g className="dim-door-width">
              <line x1={x1} y1={oy + s(dh) + 2} x2={x1} y2={dimY + tickLen * 0.5} stroke="#000" strokeWidth="0.3" />
              <line x1={x2} y1={oy + s(dh) + 2} x2={x2} y2={dimY + tickLen * 0.5} stroke="#000" strokeWidth="0.3" />
              <line x1={x1} y1={dimY} x2={x2} y2={dimY} stroke="#000" strokeWidth="0.5" />
              <DiagTick x={x1} y={dimY} />
              <DiagTick x={x2} y={dimY} />
              <text x={(x1 + x2) / 2} y={dimY - fontSize.label * 0.4}
                fontSize={fontSize.label} textAnchor="middle" fill="#000" fontWeight="bold">
                {formatDim(dw)}
              </text>
              <text x={(x1 + x2) / 2} y={dimY + fontSize.small * 1.4}
                fontSize={fontSize.small} textAnchor="middle" fill="#000">
                DOOR WIDTH
              </text>
            </g>
          )
        })()}

        {/* --- REQ. SIDEROOM callouts below drawing --- */}
        {(() => {
          const dimY = oy + s(dh) + dimLineSpacing * 1.8
          // Left sideroom: from sideroom extent to the door opening edge
          const lx1 = ox - s(sr)
          const lx2 = ox
          // Right sideroom
          const rx1 = ox + s(dw)
          const rx2 = ox + s(dw + sr)
          return (
            <g className="dim-sideroom">
              {/* Left sideroom */}
              <line x1={lx1} y1={dimY - tickLen} x2={lx1} y2={dimY + tickLen * 0.5} stroke="#000" strokeWidth="0.3" />
              <line x1={lx2} y1={oy + s(dh) + 2} x2={lx2} y2={dimY + tickLen * 0.5} stroke="#000" strokeWidth="0.3" />
              <line x1={lx1} y1={dimY} x2={lx2} y2={dimY} stroke="#000" strokeWidth="0.5" />
              <DiagTick x={lx1} y={dimY} />
              <DiagTick x={lx2} y={dimY} />
              <text x={(lx1 + lx2) / 2} y={dimY - fontSize.tiny * 0.8}
                fontSize={fontSize.tiny} textAnchor="middle" fill="#000">
                REQ. SIDEROOM
              </text>
              <text x={(lx1 + lx2) / 2} y={dimY + fontSize.small * 1.2}
                fontSize={fontSize.small} textAnchor="middle" fill="#000" fontWeight="bold">
                {formatDim(sr)}
              </text>

              {/* DOOR OPENING label in center (door size = opening size) */}
              <line x1={lx2} y1={dimY} x2={rx1} y2={dimY} stroke="#000" strokeWidth="0.5" />
              <DiagTick x={lx2} y={dimY} />
              <DiagTick x={rx1} y={dimY} />
              <text x={(lx2 + rx1) / 2} y={dimY - fontSize.tiny * 0.8}
                fontSize={fontSize.tiny} textAnchor="middle" fill="#000">
                DOOR OPENING
              </text>
              <text x={(lx2 + rx1) / 2} y={dimY + fontSize.small * 1.2}
                fontSize={fontSize.small} textAnchor="middle" fill="#000" fontWeight="bold">
                {formatDim(dw)}
              </text>

              {/* Right sideroom */}
              <line x1={rx1} y1={oy + s(dh) + 2} x2={rx1} y2={dimY + tickLen * 0.5} stroke="#000" strokeWidth="0.3" />
              <line x1={rx2} y1={dimY - tickLen} x2={rx2} y2={dimY + tickLen * 0.5} stroke="#000" strokeWidth="0.3" />
              <line x1={rx1} y1={dimY} x2={rx2} y2={dimY} stroke="#000" strokeWidth="0.5" />
              <DiagTick x={rx1} y={dimY} />
              <DiagTick x={rx2} y={dimY} />
              <text x={(rx1 + rx2) / 2} y={dimY - fontSize.tiny * 0.8}
                fontSize={fontSize.tiny} textAnchor="middle" fill="#000">
                REQ. SIDEROOM
              </text>
              <text x={(rx1 + rx2) / 2} y={dimY + fontSize.small * 1.2}
                fontSize={fontSize.small} textAnchor="middle" fill="#000" fontWeight="bold">
                {formatDim(sr)}
              </text>

              {/* Overall width below */}
              {(() => {
                const overallY = dimY + fontSize.small * 3
                return (
                  <g>
                    <line x1={lx1} y1={overallY} x2={rx2} y2={overallY} stroke="#000" strokeWidth="0.5" />
                    <DiagTick x={lx1} y={overallY} />
                    <DiagTick x={rx2} y={overallY} />
                    <text x={(lx1 + rx2) / 2} y={overallY + fontSize.small * 1.2}
                      fontSize={fontSize.small} textAnchor="middle" fill="#000" fontWeight="bold">
                      {formatDim(dw + sr * 2)}
                    </text>
                  </g>
                )
              })()}

              {/* Application label */}
              <text x={(lx1 + rx2) / 2} y={dimY + fontSize.small * 5.5}
                fontSize={fontSize.small} textAnchor="middle" fill="#000" fontWeight="bold">
                {applicationLabel}
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
              <line x1={ox + s(dw + fw + layout.wallThickness) + 2} y1={y1} x2={dimX + tickLen * 0.5} y2={y1}
                stroke="#000" strokeWidth="0.3" />
              <line x1={ox + s(dw + fw + layout.wallThickness) + 2} y1={y2} x2={dimX + tickLen * 0.5} y2={y2}
                stroke="#000" strokeWidth="0.3" />
              <line x1={dimX} y1={y1} x2={dimX} y2={y2} stroke="#000" strokeWidth="0.5" />
              <DiagTick x={dimX} y={y1} />
              <DiagTick x={dimX} y={y2} />
              <text
                x={dimX + fontSize.label * 1.2} y={(y1 + y2) / 2}
                fontSize={fontSize.label} fill="#000" fontWeight="bold"
                transform={`rotate(-90, ${dimX + fontSize.label * 1.2}, ${(y1 + y2) / 2})`}
                textAnchor="middle"
              >
                {formatDim(dh)} DOOR HEIGHT
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
              <line x1={dimX - tickLen * 0.5} y1={y1} x2={ox - s(fw + layout.wallThickness) - 2} y2={y1}
                stroke="#000" strokeWidth="0.3" />
              <line x1={dimX - tickLen * 0.5} y1={y2} x2={ox - s(fw + layout.wallThickness) - 2} y2={y2}
                stroke="#000" strokeWidth="0.3" />
              <line x1={dimX} y1={y1} x2={dimX} y2={y2} stroke="#000" strokeWidth="0.5" />
              <DiagTick x={dimX} y={y1} />
              <DiagTick x={dimX} y={y2} />
              <text
                x={dimX - fontSize.label * 1.2} y={(y1 + y2) / 2}
                fontSize={fontSize.label} fill="#000" fontWeight="bold"
                transform={`rotate(-90, ${dimX - fontSize.label * 1.2}, ${(y1 + y2) / 2})`}
                textAnchor="middle"
              >
                {formatDim(clHeight)}
              </text>
              <text
                x={dimX - fontSize.label * 1.2 - fontSize.small * 1.4} y={(y1 + y2) / 2}
                fontSize={fontSize.small} fill="#000"
                transform={`rotate(-90, ${dimX - fontSize.label * 1.2 - fontSize.small * 1.4}, ${(y1 + y2) / 2})`}
                textAnchor="middle"
              >
                CENTRELINE OF SHAFT
              </text>
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* JAMB DETAIL CALLOUT (bottom-left corner)                        */}
        {/* ================================================================ */}
        {(() => {
          const detailX = fontSize.label * 1.5
          const detailY = layout.svgH - ui.baseUnit * 11
          const ds = calloutScale
          const boxW = 40 * ds
          const boxH = 28 * ds
          return (
            <g className="jamb-detail" transform={`translate(${detailX}, ${detailY})`}>
              <text x="0" y={-fontSize.small * 0.8} fontSize={fontSize.label} fontWeight="bold" fill="#000">
                JAMB DETAIL
              </text>
              <rect x="0" y="0" width={boxW} height={boxH}
                fill="none" stroke="#000" strokeWidth="0.8" />

              {/* Wall section (hatched) */}
              <rect x={0} y={0} width={8 * ds} height={boxH}
                fill="url(#fd-hatch)" stroke="#000" strokeWidth="0.5" />

              {/* Jamb section */}
              <rect x={8 * ds} y={2 * ds} width={fw * ds} height={boxH - 4 * ds}
                fill={isSteel ? 'url(#fd-steelHatch)' : 'url(#fd-woodHatch)'}
                stroke="#000" strokeWidth="0.5" />

              {/* Weather strip */}
              <line x1={(8 + fw) * ds + ds * 0.5} y1={4 * ds} x2={(8 + fw) * ds + ds * 0.5} y2={boxH - 4 * ds}
                stroke="#000" strokeWidth={ds * 0.8} />
              {/* Leader line to WEATHER STRIP label */}
              <line x1={(8 + fw + 1) * ds} y1={boxH / 2 - 2 * ds}
                x2={(8 + fw + 6) * ds} y2={boxH / 2 - 4 * ds}
                stroke="#000" strokeWidth="0.3" />
              <text x={(8 + fw + 6.5) * ds} y={boxH / 2 - 4 * ds + fontSize.tiny * 0.3}
                fontSize={fontSize.tiny} fill="#000">WEATHER STRIP</text>

              {/* Steel end cap */}
              <rect x={(8 + fw + 2) * ds} y={boxH - 5 * ds} width={4 * ds} height={3 * ds}
                fill="none" stroke="#000" strokeWidth="0.5" />
              <line x1={(8 + fw + 4) * ds} y1={boxH - 3.5 * ds}
                x2={(8 + fw + 9) * ds} y2={boxH - 2 * ds}
                stroke="#000" strokeWidth="0.3" />
              <text x={(8 + fw + 9.5) * ds} y={boxH - 2 * ds + fontSize.tiny * 0.3}
                fontSize={fontSize.tiny} fill="#000">STEEL END CAP</text>

              {/* Fastener label */}
              <line x1={4 * ds} y1={boxH / 2}
                x2={(8 + fw + 6) * ds} y2={boxH / 2 + 3 * ds}
                stroke="#000" strokeWidth="0.3" />
              <text x={(8 + fw + 6.5) * ds} y={boxH / 2 + 3 * ds + fontSize.tiny * 0.3}
                fontSize={fontSize.tiny} fill="#000">RAMSET FASTENED</text>
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* OPTIONAL EXTRAS LIST (right side)                               */}
        {/* ================================================================ */}
        {(() => {
          const listX = rightPanelX
          const listY = oy + fontSize.label * 2
          const lineH = fontSize.small * 1.5
          return (
            <g className="optional-extras">
              <text x={listX} y={listY - fontSize.label * 0.5}
                fontSize={fontSize.label} fontWeight="bold" fill="#000"
                textDecoration="underline">
                OPTIONAL EXTRAS
              </text>
              {optionalExtras.map((item, i) => (
                <text key={`opt-${i}`} x={listX} y={listY + lineH * (i + 0.5)}
                  fontSize={fontSize.tiny} fill="#000">
                  {'\u25A1'} {item}
                </text>
              ))}
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* PANEL PROFILE CALLOUT (top-right)                               */}
        {/* ================================================================ */}
        {(() => {
          const profX = rightPanelX
          const profY = oy - s(layout.topClearance - 10)
          const profW = fontSize.label * 8
          const profH = fontSize.label * 3
          return (
            <g className="panel-profile">
              <text x={profX} y={profY - fontSize.small * 0.8}
                fontSize={fontSize.small} fontWeight="bold" fill="#000">
                PANEL PROFILE
              </text>
              <rect x={profX} y={profY} width={profW} height={profH}
                fill="none" stroke="#000" strokeWidth="0.5" />
              {/* Steel outer */}
              <rect x={profX} y={profY} width={profW} height={profH * 0.15}
                fill="none" stroke="#000" strokeWidth="0.4" />
              {/* Insulation core (hatched) */}
              <rect x={profX} y={profY + profH * 0.15} width={profW} height={profH * 0.7}
                fill="url(#fd-hatch)" stroke="#000" strokeWidth="0.3" opacity="0.3" />
              {/* Steel inner */}
              <rect x={profX} y={profY + profH * 0.85} width={profW} height={profH * 0.15}
                fill="none" stroke="#000" strokeWidth="0.4" />
              {/* Labels */}
              <text x={profX + profW + fontSize.tiny * 0.5} y={profY + profH * 0.1 + fontSize.tiny * 0.35}
                fontSize={fontSize.tiny} fill="#000">STEEL</text>
              <text x={profX + profW + fontSize.tiny * 0.5} y={profY + profH * 0.5 + fontSize.tiny * 0.35}
                fontSize={fontSize.tiny} fill="#000">INSULATION</text>
              <text x={profX + profW + fontSize.tiny * 0.5} y={profY + profH * 0.92 + fontSize.tiny * 0.35}
                fontSize={fontSize.tiny} fill="#000">STEEL</text>
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* TITLE BLOCK (bottom-right corner)                               */}
        {/* ================================================================ */}
        {(() => {
          const tbW = Math.max(150, ui.baseUnit * 18)
          const tbH = Math.max(100, ui.baseUnit * 12)
          const tbX = layout.svgW - tbW - fontSize.label
          const tbY = layout.svgH - tbH - fontSize.label
          const lineH = fontSize.small * 1.5
          const seriesName = doorSeries || 'GARAGE DOOR'
          return (
            <g className="title-block">
              {/* Outer border (double line effect) */}
              <rect x={tbX} y={tbY} width={tbW} height={tbH}
                fill="none" stroke="#000" strokeWidth="1.5" />
              <rect x={tbX + 2} y={tbY + 2} width={tbW - 4} height={tbH - 4}
                fill="none" stroke="#000" strokeWidth="0.5" />

              {/* Series name - large */}
              <text x={tbX + tbW / 2} y={tbY + fontSize.title * 1.8}
                fontSize={fontSize.title} fontWeight="bold" textAnchor="middle" fill="#000">
                {seriesName.toUpperCase()}
              </text>

              {/* Divider line */}
              <line x1={tbX + 4} y1={tbY + fontSize.title * 2.3}
                x2={tbX + tbW - 4} y2={tbY + fontSize.title * 2.3}
                stroke="#000" strokeWidth="0.5" />

              {/* Distributor */}
              <text x={tbX + 6} y={tbY + fontSize.title * 2.3 + lineH * 1.2}
                fontSize={fontSize.tiny} fill="#000">
                DISTRIBUTOR: OPEN DISTRIBUTION COMPANY
              </text>

              {/* Project fields */}
              <text x={tbX + 6} y={tbY + fontSize.title * 2.3 + lineH * 2.4}
                fontSize={fontSize.tiny} fill="#000">
                PROJECT NAME: ________________________________
              </text>
              <text x={tbX + 6} y={tbY + fontSize.title * 2.3 + lineH * 3.6}
                fontSize={fontSize.tiny} fill="#000">
                ARCHITECT: ________________________________
              </text>
              <text x={tbX + 6} y={tbY + fontSize.title * 2.3 + lineH * 4.8}
                fontSize={fontSize.tiny} fill="#000">
                DRAWN BY: ________________________________
              </text>

              {/* Date */}
              <text x={tbX + 6} y={tbY + fontSize.title * 2.3 + lineH * 6}
                fontSize={fontSize.tiny} fill="#000">
                DATE: ________________
              </text>

              {/* Track info */}
              <text x={tbX + tbW / 2} y={tbY + tbH - fontSize.tiny * 1.2}
                fontSize={fontSize.tiny} textAnchor="middle" fill="#000">
                {geo.trackTypeLabel} | {geo.radiusLabel} | {geo.trackSize}" TRACK
              </text>
            </g>
          )
        })()}

        {/* ================================================================ */}
        {/* NOTES LINE (bottom)                                             */}
        {/* ================================================================ */}
        <text x={fontSize.label * 1.5} y={layout.svgH - fontSize.tiny * 0.8}
          fontSize={fontSize.tiny} fill="#000">
          ALL DIMENSIONS IN FEET-INCHES. VERIFY ROUGH OPENING BEFORE INSTALLATION. MOUNT: {geo.mountType.toUpperCase()}.
        </text>
      </svg>
    </div>
  )
}

export default FramingDrawing
