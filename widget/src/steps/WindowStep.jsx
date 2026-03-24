import React, { useState, useMemo } from 'react'
import DoorPreview from '../DoorPreview'

const GLASS_PANE_TYPES = [
  { id: 'INSULATED', name: 'Insulated', description: 'Double-pane for energy efficiency' },
  { id: 'SINGLE', name: 'Single Pane', description: 'Standard single glass' },
]

const GLASS_COLORS = [
  { id: 'CLEAR', name: 'Clear', description: 'Standard clear glass', hex: '#87CEEB' },
  { id: 'ETCHED', name: 'Etched', description: 'Frosted privacy glass', hex: '#C8C8C8' },
  { id: 'SUPER_GREY', name: 'Super Grey', description: 'Dark tinted glass', hex: '#3D3D3D' },
]

const FRAME_COLOR_OPTIONS = [
  { id: 'MATCH', name: 'Match Door Color (Standard)' },
  { id: 'BLACK', name: 'Black' },
  { id: 'WHITE', name: 'White' },
]

// Calculate grid dimensions from door config
function getGridDimensions(width, height, panelDesign, doorSeries) {
  const isCraft = doorSeries === 'CRAFT'

  // Sections (rows)
  let sections
  if (isCraft) {
    sections = 3
  } else {
    const sectionHeight = height <= 84 ? 21 : 24
    sections = Math.round(height / sectionHeight)
  }

  // Columns — based on stamp type
  const stampPatterns = {
    SHXL: 'long', SH: 'standard', BCXL: 'long', BC: 'standard',
    TRAFALGAR: 'long', FLUSH: 'long', UDC: 'long',
    MUSKOKA: 'long', DENISON: 'long', GRANVILLE: 'long',
  }
  const stampType = stampPatterns[panelDesign] || 'long'

  const widthFeet = width / 12
  let longCols
  if (widthFeet <= 9) longCols = 2
  else if (widthFeet <= 12) longCols = 3
  else if (widthFeet <= 16) longCols = 4
  else if (widthFeet <= 19) longCols = 5
  else longCols = 6

  const cols = (stampType === 'standard' && !isCraft) ? longCols * 2 : longCols
  return { sections, cols }
}

export default function WindowStep({ options, family, config, onSelect, onWindowPositionsChange }) {
  const isCommercial = family?.type === 'commercial'
  const isAluminium = family?.type === 'aluminium'
  const commercialWindows = family?.commercialWindows || []
  const windowInserts = family?.windowInserts || []

  const [includeWindows, setIncludeWindows] = useState(
    config.windowInsert && config.windowInsert !== 'NONE'
  )
  const [highlightStamp, setHighlightStamp] = useState(null)

  const grid = useMemo(
    () => getGridDimensions(config.width, config.height, config.panelDesign, config.doorSeries),
    [config.width, config.height, config.panelDesign, config.doorSeries]
  )

  const windowPositions = config.windowPositions || []
  const windowCount = windowPositions.length

  // Toggle a window position
  const togglePosition = (section, col) => {
    const exists = windowPositions.some(p => p.section === section && p.col === col)
    let newPositions
    if (exists) {
      newPositions = windowPositions.filter(p => !(p.section === section && p.col === col))
    } else {
      newPositions = [...windowPositions, { section, col }]
    }
    onWindowPositionsChange?.(newPositions)
  }

  const hasWindowAt = (section, col) => {
    return windowPositions.some(p => p.section === section && p.col === col)
  }

  // Quick pattern helpers
  const setTopRow = () => {
    const positions = []
    for (let c = 0; c < grid.cols; c++) positions.push({ section: 1, col: c })
    onWindowPositionsChange?.(positions)
  }

  const setLeftColumn = () => {
    const positions = []
    for (let s = 1; s <= grid.sections; s++) positions.push({ section: s, col: 0 })
    onWindowPositionsChange?.(positions)
  }

  const setRightColumn = () => {
    const positions = []
    for (let s = 1; s <= grid.sections; s++) positions.push({ section: s, col: grid.cols - 1 })
    onWindowPositionsChange?.(positions)
  }

  const clearAll = () => {
    onWindowPositionsChange?.([])
  }

  // Toggle include windows
  const handleToggleWindows = (checked) => {
    setIncludeWindows(checked)
    if (!checked) {
      onSelect('NONE', 0, null, 1)
      onWindowPositionsChange?.([])
    } else {
      // Default to plain windows (no decorative insert)
      onSelect('PLAIN_LONG', 0, config.glassColor || 'CLEAR', 1)
    }
  }

  // Handle insert type change
  const handleInsertChange = (insertId) => {
    onSelect(insertId, 0, config.glassColor || 'CLEAR', 1)
    // Keep existing positions
  }

  // ---- COMMERCIAL ----
  if (isCommercial && commercialWindows.length > 0) {
    const cwd = options.commercialWindowData || {}
    const thermopaneOptions = commercialWindows.filter(id => cwd[id] && !cwd[id].fullView)
    const fullViewOptions = commercialWindows.filter(id => cwd[id] && cwd[id].fullView)

    return (
      <div className="odc-step-content">
        <h2 className="odc-step-title">Windows</h2>
        <p className="odc-step-subtitle">Select window type for your {family?.name}</p>

        {thermopaneOptions.length > 0 && (
          <>
            <h3 className="odc-subsection-title">Thermopane Windows</h3>
            <div className="odc-window-grid">
              {thermopaneOptions.map((winId) => {
                const winInfo = cwd[winId]
                return (
                  <button key={winId}
                    className={`odc-window-card ${config.windowInsert === winId ? 'odc-selected' : ''}`}
                    onClick={() => onSelect(winId, config.windowQty || 1, 'CLEAR', config.windowSection)}>
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
                <div className="odc-commercial-window-visual"><div className="odc-no-window-icon">&#10005;</div></div>
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
                return (
                  <button key={winId}
                    className={`odc-window-card ${config.windowInsert === winId ? 'odc-selected' : ''}`}
                    onClick={() => onSelect(winId, config.windowQty || 1, 'CLEAR', config.windowSection)}>
                    <div className="odc-commercial-window-visual">
                      <div className="odc-fullview-icon">
                        <div className="odc-fullview-panes">{[1,2,3,4].map(i => <div key={i} className="odc-fullview-pane" />)}</div>
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
            <h3 className="odc-subsection-title">
              {cwd[config.windowInsert]?.fullView ? 'Number of Full View Sections' : 'Windows Per Section'}
            </h3>
            <div className="odc-size-presets">
              {[1, 2, 3, 4].map((n) => (
                <button key={n} className={`odc-size-btn ${config.windowQty === n ? 'odc-selected' : ''}`}
                  onClick={() => onSelect(config.windowInsert, n, config.glassColor, config.windowSection)}>
                  {n}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  // ---- RESIDENTIAL WINDOW RENDERING ----
  if (windowInserts.length === 0 && !isAluminium) {
    return (
      <div className="odc-step-content">
        <h2 className="odc-step-title">Windows</h2>
        <p className="odc-step-subtitle">Window inserts are not available for the {family?.name}.</p>
      </div>
    )
  }

  // AL976 — glass only, no inserts
  if (isAluminium) {
    return (
      <div className="odc-step-content">
        <h2 className="odc-step-title">Glass Options</h2>
        <p className="odc-step-subtitle">Choose glass type and color for your aluminum door</p>
        <h3 className="odc-subsection-title">Glass Pane Type</h3>
        <div className="odc-option-cards">
          {GLASS_PANE_TYPES.map(g => (
            <button key={g.id}
              className={`odc-option-card ${config.glassPaneType === g.id ? 'odc-selected' : ''}`}
              onClick={() => onSelect(config.windowInsert, config.windowQty, config.glassColor, config.windowSection, g.id)}>
              <strong>{g.name}</strong>
              <span className="odc-option-desc">{g.description}</span>
            </button>
          ))}
        </div>
        <h3 className="odc-subsection-title">Glass Color</h3>
        <div className="odc-color-grid">
          {GLASS_COLORS.map(g => (
            <button key={g.id}
              className={`odc-color-swatch ${config.glassColor === g.id ? 'odc-selected' : ''}`}
              onClick={() => onSelect(config.windowInsert, config.windowQty, g.id, config.windowSection, config.glassPaneType)}>
              <div className="odc-color-circle-wrap">
                <div className="odc-color-circle" style={{ backgroundColor: g.hex }} />
              </div>
              <span className="odc-color-name">{g.name}</span>
              <span className="odc-color-type">{g.description}</span>
            </button>
          ))}
        </div>
      </div>
    )
  }

  // ---- RESIDENTIAL: Full window placement UI ----
  return (
    <div className="odc-step-content">
      <h2 className="odc-step-title">Windows</h2>

      {/* Include windows toggle */}
      <label className="odc-checkbox-label">
        <input
          type="checkbox"
          checked={includeWindows}
          onChange={(e) => handleToggleWindows(e.target.checked)}
          className="odc-checkbox"
        />
        Include windows in this door
      </label>

      {includeWindows && (
        <>
          {/* 1. Select Window Positions */}
          <h3 className="odc-subsection-title">1. Select Window Positions</h3>
          <p className="odc-step-hint">Click stamps to add/remove windows</p>

          <div className="odc-window-placement-layout">
            {/* Interactive door preview */}
            <div className="odc-window-placement-preview">
              <DoorPreview
                width={config.width}
                height={config.height}
                color={config.color}
                panelDesign={config.panelDesign}
                doorType={config.doorType}
                doorSeries={config.doorSeries}
                windowInsert={config.windowInsert}
                windowPositions={windowPositions}
                windowSize={config.windowSize || 'long'}
                hasInserts={true}
                glassColor={config.glassColor || 'CLEAR'}
                windowFrameColor={config.windowFrameColor || 'MATCH'}
                showDimensions={false}
                maxWidth={280}
                interactive={true}
                onStampClick={togglePosition}
                onStampHover={(s, c) => setHighlightStamp(s === null ? null : { section: s, col: c })}
                highlightStamp={highlightStamp}
              />
              <p className="odc-placement-hint">Click any stamp to toggle window</p>
            </div>

            {/* Quick patterns + grid */}
            <div className="odc-window-placement-controls">
              <div className="odc-quick-patterns">
                <strong>Quick Patterns:</strong>
                <div className="odc-pattern-buttons">
                  <button className="odc-pattern-btn" onClick={setTopRow}>Top Row</button>
                  <button className="odc-pattern-btn" onClick={setLeftColumn}>Left Column</button>
                  <button className="odc-pattern-btn" onClick={setRightColumn}>Right Column</button>
                  <button className="odc-pattern-btn odc-pattern-clear" onClick={clearAll}>Clear All</button>
                </div>
              </div>

              <div className="odc-grid-info">
                <strong>Door Grid:</strong> {grid.sections} sections × {grid.cols} window positions
                <br />
                <strong>Windows Selected:</strong> {windowCount}
              </div>

              <p className="odc-step-hint">Or click grid cells:</p>
              <div className="odc-click-grid">
                {Array.from({ length: grid.sections }).map((_, sIdx) => (
                  <div key={sIdx} className="odc-click-grid-row">
                    {Array.from({ length: grid.cols }).map((_, cIdx) => {
                      const section = sIdx + 1
                      const active = hasWindowAt(section, cIdx)
                      return (
                        <button
                          key={cIdx}
                          className={`odc-grid-cell ${active ? 'odc-grid-cell-active' : ''}`}
                          onClick={() => togglePosition(section, cIdx)}
                          title={`Section ${section}, Column ${cIdx + 1}`}
                        />
                      )
                    })}
                    <span className="odc-grid-label">S{sIdx + 1}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 2. Window Insert Style */}
          <h3 className="odc-subsection-title">2. Window Insert Style</h3>
          <div className="odc-insert-options">
            <button
              className={`odc-insert-btn ${!config.windowInsert || config.windowInsert === 'PLAIN_LONG' ? 'odc-selected' : ''}`}
              onClick={() => handleInsertChange('PLAIN_LONG')}>
              No Insert
            </button>
            {windowInserts.map((insertId) => {
              const info = options.windowData?.[insertId]
              if (!info) return null
              return (
                <button key={insertId}
                  className={`odc-insert-btn ${config.windowInsert === insertId ? 'odc-selected' : ''}`}
                  onClick={() => handleInsertChange(insertId)}>
                  {info.name}
                </button>
              )
            })}
          </div>

          {/* 3. Glass Pane Type */}
          <h3 className="odc-subsection-title">3. Glass Pane Type</h3>
          <div className="odc-option-cards">
            {GLASS_PANE_TYPES.map(g => (
              <button key={g.id}
                className={`odc-option-card ${config.glassPaneType === g.id ? 'odc-selected' : ''}`}
                onClick={() => onSelect(config.windowInsert, config.windowQty, config.glassColor, config.windowSection, g.id)}>
                <strong>{g.name}</strong>
                <span className="odc-option-desc">{g.description}</span>
              </button>
            ))}
          </div>

          {/* 4. Glass Color */}
          <h3 className="odc-subsection-title">4. Glass Color</h3>
          <div className="odc-color-grid">
            {GLASS_COLORS.map(g => (
              <button key={g.id}
                className={`odc-color-swatch ${config.glassColor === g.id ? 'odc-selected' : ''}`}
                onClick={() => onSelect(config.windowInsert, config.windowQty, g.id, config.windowSection, config.glassPaneType)}>
                <div className="odc-color-circle-wrap">
                  <div className="odc-color-circle" style={{ backgroundColor: g.hex }} />
                </div>
                <span className="odc-color-name">{g.name}</span>
                <span className="odc-color-type">{g.description}</span>
              </button>
            ))}
          </div>

          {/* 5. Window Frame Color */}
          <h3 className="odc-subsection-title">5. Window Frame Color</h3>
          <select
            className="odc-select"
            value={config.windowFrameColor || 'MATCH'}
            onChange={(e) => {
              // Propagate frame color change via onSelect with current values
              onSelect(config.windowInsert, config.windowQty, config.glassColor, config.windowSection, config.glassPaneType, e.target.value)
            }}
          >
            {FRAME_COLOR_OPTIONS.map(opt => (
              <option key={opt.id} value={opt.id}>{opt.name}</option>
            ))}
          </select>
        </>
      )}
    </div>
  )
}
