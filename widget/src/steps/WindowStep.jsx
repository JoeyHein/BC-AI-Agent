import React, { useState } from 'react'
import DoorPreview from '../DoorPreview'

// Glass type options by context
const RESIDENTIAL_GLASS = ['INSULATED_CLEAR', 'INSULATED_ETCHED', 'SINGLE_CLEAR']
const COMMERCIAL_THERMOPANE_GLASS = ['THERMAL_CLEAR']
const FULLVIEW_GLASS = ['CLEAR', 'ETCHED', 'SUPER_GREY']

// Simple SVG window insert preview (standalone, no door)
function WindowInsertSwatch({ windowId, windowData, size = 100 }) {
  const info = windowData?.[windowId]
  if (!info || windowId === 'NONE') {
    return (
      <div style={{ width: size, height: size * 0.7, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <svg width={size * 0.5} height={size * 0.5} viewBox="0 0 40 40">
          <line x1="8" y1="8" x2="32" y2="32" stroke="#666" strokeWidth="2" />
          <line x1="32" y1="8" x2="8" y2="32" stroke="#666" strokeWidth="2" />
          <rect x="4" y="4" width="32" height="32" rx="2" fill="none" stroke="#444" strokeWidth="1.5" />
        </svg>
      </div>
    )
  }

  const { grid, arched, prairie } = info
  const rows = grid?.[0] || 2
  const cols = grid?.[1] || 4
  const w = size
  const h = size * 0.65
  const pad = 4
  const frameW = w - pad * 2
  const frameH = h - pad * 2
  const cellW = frameW / cols
  const cellH = frameH / rows
  const archH = arched ? 8 : 0
  const glassColor = '#87CEEB'

  return (
    <svg width={w} height={h + archH} viewBox={`0 0 ${w} ${h + archH}`}>
      {/* Arch */}
      {arched && (
        <path
          d={`M ${pad} ${pad + archH} Q ${w / 2} ${pad - 4} ${w - pad} ${pad + archH}`}
          fill="none" stroke="#888" strokeWidth="1.5"
        />
      )}
      {/* Frame */}
      <rect x={pad} y={pad + archH} width={frameW} height={frameH} rx="1" fill="#333" stroke="#888" strokeWidth="1.5" />
      {/* Glass panes */}
      {Array.from({ length: rows }).map((_, r) =>
        Array.from({ length: cols }).map((_, c) => (
          <rect
            key={`${r}-${c}`}
            x={pad + c * cellW + 1.5}
            y={pad + archH + r * cellH + 1.5}
            width={cellW - 3}
            height={cellH - 3}
            rx="0.5"
            fill={glassColor}
            opacity={0.5}
          />
        ))
      )}
      {/* Grid lines */}
      {Array.from({ length: cols - 1 }).map((_, c) => (
        <line key={`v${c}`} x1={pad + (c + 1) * cellW} y1={pad + archH} x2={pad + (c + 1) * cellW} y2={h} stroke="#888" strokeWidth="1" />
      ))}
      {Array.from({ length: rows - 1 }).map((_, r) => (
        <line key={`h${r}`} x1={pad} y1={pad + archH + (r + 1) * cellH} x2={w - pad} y2={pad + archH + (r + 1) * cellH} stroke="#888" strokeWidth="1" />
      ))}
      {/* Prairie corners */}
      {prairie && Array.from({ length: rows }).map((_, r) =>
        Array.from({ length: cols }).map((_, c) => (
          <rect
            key={`p${r}-${c}`}
            x={pad + c * cellW + 3}
            y={pad + archH + r * cellH + 3}
            width={6}
            height={6}
            fill="#888"
            opacity={0.5}
          />
        ))
      )}
    </svg>
  )
}

export default function WindowStep({ options, family, config, onSelect, onWindowPositionsChange }) {
  const isCommercial = family?.type === 'commercial'
  const isAluminium = family?.type === 'aluminium'
  const commercialWindows = family?.commercialWindows || []
  const windowInserts = family?.windowInserts || []

  const [highlightStamp, setHighlightStamp] = useState(null)

  const getWindowSize = (windowId) => {
    if (!windowId || windowId === 'NONE') return 'long'
    const wd = options.windowData?.[windowId]
    return wd?.size || 'long'
  }

  const currentWindowSize = getWindowSize(config.windowInsert)

  const getGlassOptions = () => {
    if (isAluminium) return FULLVIEW_GLASS
    if (isCommercial) {
      const cwd = options.commercialWindowData || {}
      const selected = cwd[config.windowInsert]
      if (selected?.fullView) return FULLVIEW_GLASS
      if (config.windowInsert && config.windowInsert !== 'NONE') return COMMERCIAL_THERMOPANE_GLASS
      return []
    }
    if (config.windowInsert && config.windowInsert !== 'NONE') return RESIDENTIAL_GLASS
    return []
  }

  const glassOptions = getGlassOptions()

  const handleStampClick = (section, col) => {
    if (!config.windowInsert || config.windowInsert === 'NONE') return
    const positions = config.windowPositions || []
    const exists = positions.some(p => p.section === section && p.col === col)
    let newPositions
    if (exists) {
      newPositions = positions.filter(p => !(p.section === section && p.col === col))
    } else {
      newPositions = [...positions, { section, col }]
    }
    if (onWindowPositionsChange) {
      onWindowPositionsChange(newPositions)
    }
  }

  const handleStampHover = (section, col) => {
    if (section === null) {
      setHighlightStamp(null)
    } else {
      setHighlightStamp({ section, col })
    }
  }

  const windowPositionCount = (config.windowPositions || []).length
  const hasWindowInsertSelected = config.windowInsert && config.windowInsert !== 'NONE'

  // Glass type renderer (shared between commercial and residential)
  const renderGlassOptions = () => {
    if (glassOptions.length === 0) return null
    const glassColors = {
      CLEAR: '#A8D8EA', ETCHED: '#D3D3D3', SUPER_GREY: '#4A4A4A',
      INSULATED_CLEAR: '#A8D8EA', INSULATED_ETCHED: '#D3D3D3', SINGLE_CLEAR: '#BDE0EE',
      THERMAL_CLEAR: '#A8D8EA',
    }
    return (
      <>
        <h3 className="odc-subsection-title">Glass Type</h3>
        <div className="odc-color-grid">
          {glassOptions.map((glassId) => {
            const glassInfo = options.glassData?.[glassId]
            if (!glassInfo) return null
            const isSelected = config.glassColor === glassId
            return (
              <button
                key={glassId}
                className={`odc-color-swatch ${isSelected ? 'odc-selected' : ''}`}
                onClick={() => onSelect(config.windowInsert, config.windowQty, glassId, config.windowSection)}
                title={glassInfo.name}
              >
                <div className="odc-color-circle-wrap">
                  <div className="odc-color-circle odc-glass" style={{ backgroundColor: glassColors[glassId] || '#A8D8EA' }} />
                </div>
                <span className="odc-color-name">{glassInfo.name}</span>
              </button>
            )
          })}
        </div>
      </>
    )
  }

  // ---- COMMERCIAL WINDOW RENDERING ----
  if (isCommercial && commercialWindows.length > 0) {
    const cwd = options.commercialWindowData || {}
    const thermopaneOptions = commercialWindows.filter(id => cwd[id] && !cwd[id].fullView)
    const fullViewOptions = commercialWindows.filter(id => cwd[id] && cwd[id].fullView)

    return (
      <div className="odc-step-content">
        <h2 className="odc-step-title">Choose Your Windows</h2>
        <p className="odc-step-subtitle">Select window type for your {family?.name}</p>

        {thermopaneOptions.length > 0 && (
          <>
            <h3 className="odc-subsection-title">Thermopane Windows</h3>
            <div className="odc-window-grid">
              {thermopaneOptions.map((winId) => {
                const winInfo = cwd[winId]
                const isSelected = config.windowInsert === winId
                return (
                  <button key={winId} className={`odc-window-card ${isSelected ? 'odc-selected' : ''}`}
                    onClick={() => onSelect(winId, config.windowQty || 1, 'THERMAL_CLEAR', config.windowSection)}>
                    <div className="odc-commercial-window-visual">
                      <div className="odc-commercial-window-frame">
                        <div className="odc-commercial-window-glass" style={{
                          width: `${Math.min(winInfo.width * 2.5, 100)}px`,
                          height: `${Math.min(winInfo.height * 2.5, 60)}px`,
                        }} />
                      </div>
                      <div className="odc-commercial-window-dims">{winInfo.width}" x {winInfo.height}"</div>
                    </div>
                    <span className="odc-window-name">{winInfo.name}</span>
                  </button>
                )
              })}
              <button className={`odc-window-card ${!config.windowInsert || config.windowInsert === 'NONE' ? 'odc-selected' : ''}`}
                onClick={() => onSelect('NONE', 0, null, 1)}>
                <div className="odc-commercial-window-visual">
                  <div className="odc-no-window-icon">&#10005;</div>
                </div>
                <span className="odc-window-name">No Windows</span>
              </button>
            </div>
          </>
        )}

        {fullViewOptions.length > 0 && (
          <>
            <h3 className="odc-subsection-title">Full View Sections</h3>
            <div className="odc-window-grid">
              {fullViewOptions.map((winId) => {
                const winInfo = cwd[winId]
                const isSelected = config.windowInsert === winId
                return (
                  <button key={winId} className={`odc-window-card ${isSelected ? 'odc-selected' : ''}`}
                    onClick={() => onSelect(winId, config.windowQty || 1, 'CLEAR', config.windowSection)}>
                    <div className="odc-commercial-window-visual">
                      <div className="odc-fullview-icon">
                        <div className="odc-fullview-panes">
                          {[1,2,3,4].map(i => <div key={i} className="odc-fullview-pane" />)}
                        </div>
                      </div>
                    </div>
                    <span className="odc-window-name">{winInfo.name}</span>
                  </button>
                )
              })}
            </div>
          </>
        )}

        {config.windowInsert && config.windowInsert !== 'NONE' && (
          <div className="odc-qty-section">
            {cwd[config.windowInsert]?.fullView ? (
              <>
                <h3 className="odc-subsection-title">Number of Full View Sections</h3>
                <div className="odc-size-presets">
                  {[1, 2, 3, 4].map((n) => (
                    <button key={n} className={`odc-size-btn ${config.windowQty === n ? 'odc-selected' : ''}`}
                      onClick={() => onSelect(config.windowInsert, n, config.glassColor, config.windowSection)}>
                      {n}
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <>
                <h3 className="odc-subsection-title">Windows Per Section</h3>
                <div className="odc-size-presets">
                  {[1, 2, 3, 4].map((n) => (
                    <button key={n} className={`odc-size-btn ${config.windowQty === n ? 'odc-selected' : ''}`}
                      onClick={() => onSelect(config.windowInsert, n, config.glassColor, config.windowSection)}>
                      {n}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {hasWindowInsertSelected && renderGlassOptions()}
      </div>
    )
  }

  // ---- RESIDENTIAL WINDOW RENDERING ----
  if (windowInserts.length === 0) {
    return (
      <div className="odc-step-content">
        <h2 className="odc-step-title">Window Inserts</h2>
        <p className="odc-step-subtitle">Window inserts are not available for the {family?.name}. Continue to the next step.</p>
      </div>
    )
  }

  const allOptions = [...windowInserts, 'NONE']

  return (
    <div className="odc-step-content">
      <h2 className="odc-step-title">Choose Your Windows</h2>
      <p className="odc-step-subtitle">
        {hasWindowInsertSelected
          ? 'Click the door panels below to place your windows'
          : 'Select a window insert style'}
      </p>

      {/* Insert type selection — standalone swatches, NOT on a door */}
      <div className="odc-window-grid">
        {allOptions.map((windowId) => {
          const windowInfo = options.windowData?.[windowId]
          if (!windowInfo) return null
          const isSelected = config.windowInsert === windowId || (!config.windowInsert && windowId === 'NONE')
          const isNone = windowId === 'NONE'

          return (
            <button
              key={windowId}
              className={`odc-window-card ${isSelected ? 'odc-selected' : ''}`}
              onClick={() => onSelect(isNone ? 'NONE' : windowId, 0, config.glassColor, 1)}
            >
              <div className="odc-window-preview" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 80 }}>
                <WindowInsertSwatch windowId={windowId} windowData={options.windowData} size={120} />
              </div>
              <span className="odc-window-name">{windowInfo.name}</span>
            </button>
          )
        })}
      </div>

      {/* Interactive door grid — only shown AFTER insert is selected */}
      {hasWindowInsertSelected && (
        <div className="odc-window-placement">
          <h3 className="odc-subsection-title">Place Your Windows</h3>
          <p className="odc-placement-instructions">
            Click on the door panels to place or remove windows
          </p>
          <div className="odc-placement-grid">
            <DoorPreview
              width={config.width}
              height={config.height}
              color={config.color}
              panelDesign={config.panelDesign}
              doorType={config.doorType}
              doorSeries={config.doorSeries}
              windowInsert={config.windowInsert}
              windowPositions={config.windowPositions || []}
              windowSize={currentWindowSize}
              hasInserts={true}
              glassColor={config.glassColor || 'CLEAR'}
              showDimensions={false}
              maxWidth={500}
              scale={1.3}
              interactive={true}
              onStampClick={handleStampClick}
              onStampHover={handleStampHover}
              highlightStamp={highlightStamp}
            />
          </div>
          <div className="odc-placement-count">
            {windowPositionCount === 0
              ? 'No windows placed yet — click a panel above'
              : `${windowPositionCount} window${windowPositionCount !== 1 ? 's' : ''} placed`
            }
          </div>
        </div>
      )}

      {/* Glass type */}
      {hasWindowInsertSelected && renderGlassOptions()}
    </div>
  )
}
