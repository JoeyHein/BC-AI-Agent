import React, { useState } from 'react'
import DoorPreview from '../DoorPreview'

// Glass type options by context
const RESIDENTIAL_GLASS = ['INSULATED_CLEAR', 'INSULATED_ETCHED', 'SINGLE_CLEAR']
const COMMERCIAL_THERMOPANE_GLASS = ['THERMAL_CLEAR']
const FULLVIEW_GLASS = ['CLEAR', 'ETCHED', 'SUPER_GREY']

export default function WindowStep({ options, family, config, onSelect, onWindowPositionsChange }) {
  const isCommercial = family?.type === 'commercial'
  const isAluminium = family?.type === 'aluminium'
  const commercialWindows = family?.commercialWindows || []
  const windowInserts = family?.windowInserts || []

  const [highlightStamp, setHighlightStamp] = useState(null)

  // Determine window size from options windowData
  const getWindowSize = (windowId) => {
    if (!windowId || windowId === 'NONE') return 'long'
    const wd = options.windowData?.[windowId]
    return wd?.size || 'long'
  }

  const currentWindowSize = getWindowSize(config.windowInsert)

  // Determine which glass options to show
  const getGlassOptions = () => {
    if (isAluminium) return FULLVIEW_GLASS
    if (isCommercial) {
      const cwd = options.commercialWindowData || {}
      const selected = cwd[config.windowInsert]
      if (selected?.fullView) return FULLVIEW_GLASS
      if (config.windowInsert) return COMMERCIAL_THERMOPANE_GLASS
      return []
    }
    // Residential with windows selected
    if (config.windowInsert && config.windowInsert !== 'NONE') return RESIDENTIAL_GLASS
    return []
  }

  const glassOptions = getGlassOptions()

  // Handle stamp click — toggle window position
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

  // Handle stamp hover
  const handleStampHover = (section, col) => {
    if (section === null) {
      setHighlightStamp(null)
    } else {
      setHighlightStamp({ section, col })
    }
  }

  const windowPositionCount = (config.windowPositions || []).length
  const hasWindowInsertSelected = config.windowInsert && config.windowInsert !== 'NONE'

  // ---- COMMERCIAL WINDOW RENDERING ----
  if (isCommercial && commercialWindows.length > 0) {
    const cwd = options.commercialWindowData || {}
    // Split into thermopane and full-view
    const thermopaneOptions = commercialWindows.filter(id => cwd[id] && !cwd[id].fullView)
    const fullViewOptions = commercialWindows.filter(id => cwd[id] && cwd[id].fullView)

    return (
      <div className="odc-step-content">
        <h2 className="odc-step-title">Choose Your Windows</h2>
        <p className="odc-step-subtitle">Select window type for your {family?.name}</p>

        {/* Thermopane options */}
        {thermopaneOptions.length > 0 && (
          <>
            <h3 className="odc-subsection-title">Thermopane Windows</h3>
            <div className="odc-window-grid">
              {thermopaneOptions.map((winId) => {
                const winInfo = cwd[winId]
                const isSelected = config.windowInsert === winId
                return (
                  <button
                    key={winId}
                    className={`odc-window-card ${isSelected ? 'odc-selected' : ''}`}
                    onClick={() => onSelect(winId, config.windowQty || 1, 'THERMAL_CLEAR', config.windowSection)}
                  >
                    <div className="odc-commercial-window-visual">
                      <div className="odc-commercial-window-frame">
                        <div className="odc-commercial-window-glass" style={{
                          width: `${Math.min(winInfo.width * 2.5, 100)}px`,
                          height: `${Math.min(winInfo.height * 2.5, 60)}px`,
                        }} />
                      </div>
                      <div className="odc-commercial-window-dims">
                        {winInfo.width}" x {winInfo.height}"
                      </div>
                    </div>
                    <span className="odc-window-name">{winInfo.name}</span>
                  </button>
                )
              })}
              {/* No windows option */}
              <button
                className={`odc-window-card ${!config.windowInsert ? 'odc-selected' : ''}`}
                onClick={() => onSelect('NONE', 0, null, 1)}
              >
                <div className="odc-commercial-window-visual">
                  <div className="odc-no-window-icon">&#10005;</div>
                </div>
                <span className="odc-window-name">No Windows</span>
              </button>
            </div>
          </>
        )}

        {/* Full View options */}
        {fullViewOptions.length > 0 && (
          <>
            <h3 className="odc-subsection-title">Full View Sections</h3>
            <div className="odc-window-grid">
              {fullViewOptions.map((winId) => {
                const winInfo = cwd[winId]
                const isSelected = config.windowInsert === winId
                return (
                  <button
                    key={winId}
                    className={`odc-window-card ${isSelected ? 'odc-selected' : ''}`}
                    onClick={() => onSelect(winId, config.windowQty || 1, 'CLEAR', config.windowSection)}
                  >
                    <div className="odc-commercial-window-visual">
                      <div className="odc-fullview-icon">
                        <div className="odc-fullview-panes">
                          <div className="odc-fullview-pane" />
                          <div className="odc-fullview-pane" />
                          <div className="odc-fullview-pane" />
                          <div className="odc-fullview-pane" />
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

        {/* Quantity / section count selector for selected commercial window */}
        {config.windowInsert && config.windowInsert !== 'NONE' && (
          <div className="odc-qty-section">
            {cwd[config.windowInsert]?.fullView ? (
              <>
                <h3 className="odc-subsection-title">Number of Full View Sections</h3>
                <div className="odc-size-presets">
                  {[1, 2, 3, 4].map((n) => (
                    <button
                      key={n}
                      className={`odc-size-btn ${config.windowQty === n ? 'odc-selected' : ''}`}
                      onClick={() => onSelect(config.windowInsert, n, config.glassColor, config.windowSection)}
                    >
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
                    <button
                      key={n}
                      className={`odc-size-btn ${config.windowQty === n ? 'odc-selected' : ''}`}
                      onClick={() => onSelect(config.windowInsert, n, config.glassColor, config.windowSection)}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {/* Glass type for commercial */}
        {config.windowInsert && config.windowInsert !== 'NONE' && glassOptions.length > 0 && (
          <>
            <h3 className="odc-subsection-title">Glass Type</h3>
            <div className="odc-color-grid">
              {glassOptions.map((glassId) => {
                const glassInfo = options.glassData?.[glassId]
                if (!glassInfo) return null
                const isSelected = config.glassColor === glassId
                const glassColors = {
                  CLEAR: '#A8D8EA', ETCHED: '#D3D3D3', SUPER_GREY: '#4A4A4A',
                  INSULATED_CLEAR: '#A8D8EA', INSULATED_ETCHED: '#D3D3D3', SINGLE_CLEAR: '#BDE0EE',
                  THERMAL_CLEAR: '#A8D8EA',
                }
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
                    <span className="odc-color-type">{glassInfo.description}</span>
                  </button>
                )
              })}
            </div>
          </>
        )}
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

  // Add NONE option
  const allOptions = [...windowInserts, 'NONE']

  return (
    <div className="odc-step-content">
      <h2 className="odc-step-title">Choose Your Windows</h2>
      <p className="odc-step-subtitle">Select a window insert style, then click panels to place them</p>
      <div className="odc-window-grid">
        {allOptions.map((windowId) => {
          const windowInfo = options.windowData[windowId]
          if (!windowInfo) return null
          const isSelected = config.windowInsert === windowId || (!config.windowInsert && windowId === 'NONE')
          const isNone = windowId === 'NONE'

          return (
            <button
              key={windowId}
              className={`odc-window-card ${isSelected ? 'odc-selected' : ''}`}
              onClick={() => onSelect(isNone ? 'NONE' : windowId, 0, config.glassColor, 1)}
            >
              <div className="odc-window-preview">
                <DoorPreview
                  width={config.width}
                  height={config.height}
                  color={config.color}
                  panelDesign={config.panelDesign}
                  doorType={config.doorType}
                  doorSeries={config.doorSeries}
                  windowInsert={isNone ? null : windowId}
                  windowSection={1}
                  windowSize={getWindowSize(windowId)}
                  hasInserts={true}
                  showDimensions={false}
                  maxWidth={140}
                />
              </div>
              <span className="odc-window-name">{windowInfo.name}</span>
            </button>
          )
        })}
      </div>

      {/* Interactive door grid for placing windows */}
      {hasWindowInsertSelected && (
        <div className="odc-window-placement">
          <h3 className="odc-subsection-title">Place Your Windows</h3>
          <p className="odc-placement-instructions">
            Click panels to place or remove windows
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
              maxWidth={480}
              scale={1.2}
              interactive={true}
              onStampClick={handleStampClick}
              onStampHover={handleStampHover}
              highlightStamp={highlightStamp}
            />
          </div>
          <div className="odc-placement-count">
            {windowPositionCount === 0
              ? 'No windows placed yet'
              : `${windowPositionCount} window${windowPositionCount !== 1 ? 's' : ''} selected`
            }
          </div>
        </div>
      )}

      {/* Glass type for residential */}
      {glassOptions.length > 0 && (
        <>
          <h3 className="odc-subsection-title">Glass Type</h3>
          <div className="odc-color-grid">
            {glassOptions.map((glassId) => {
              const glassInfo = options.glassData?.[glassId]
              if (!glassInfo) return null
              const isSelected = config.glassColor === glassId
              const glassColors = {
                CLEAR: '#A8D8EA', ETCHED: '#D3D3D3', SUPER_GREY: '#4A4A4A',
                INSULATED_CLEAR: '#A8D8EA', INSULATED_ETCHED: '#D3D3D3', SINGLE_CLEAR: '#BDE0EE',
                THERMAL_CLEAR: '#A8D8EA',
              }
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
                  <span className="odc-color-type">{glassInfo.description}</span>
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
