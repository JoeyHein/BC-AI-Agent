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
    // Only show 24X12_THERMOPANE and V130G/V230G
    const showOptions = commercialWindows.filter(id => {
      if (id === '24X12_THERMOPANE') return true
      if (cwd[id]?.fullView) return true
      return false
    })
    const thermopaneOptions = showOptions.filter(id => !cwd[id]?.fullView)
    const fullViewOptions = showOptions.filter(id => cwd[id]?.fullView)

    // Panel count from door height
    const sectionHeight = config.height <= 84 ? 21 : 24
    const panelCount = Math.round(config.height / sectionHeight)
    const defaultSection = panelCount >= 3 ? panelCount - 2 : 1

    // Recommended window qty based on door width and window size
    const calcRecommended = () => {
      const winInfo = cwd[config.windowInsert]
      if (!winInfo || winInfo.fullView) return 1
      const windowWidth = winInfo.width || 24
      const doorWidth = config.width
      const optimalSpacing = 10
      return Math.max(1, Math.floor((doorWidth - optimalSpacing) / (windowWidth + optimalSpacing)))
    }

    const calcSpacing = (qty) => {
      const winInfo = cwd[config.windowInsert]
      if (!winInfo || winInfo.fullView || !qty) return null
      const windowWidth = winInfo.width || 24
      const totalWindowWidth = windowWidth * qty
      const spaces = qty + 1
      if (totalWindowWidth >= config.width) return null
      return ((config.width - totalWindowWidth) / spaces).toFixed(1)
    }

    const recommended = calcRecommended()
    const currentQty = config.windowQty || 0
    const spacing = calcSpacing(currentQty)
    const hasSelection = config.windowInsert && config.windowInsert !== 'NONE'
    const isFullView = hasSelection && cwd[config.windowInsert]?.fullView

    const [includeCommWindows, setIncludeCommWindows] = useState(hasSelection)

    const handleToggle = (checked) => {
      setIncludeCommWindows(checked)
      if (!checked) {
        onSelect('NONE', 0, null, 1)
      } else {
        onSelect('24X12_THERMOPANE', recommended, 'CLEAR', defaultSection)
      }
    }

    return (
      <div className="odc-step-content">
        <h2 className="odc-step-title">Windows</h2>

        <label className="odc-checkbox-label">
          <input type="checkbox" checked={includeCommWindows} onChange={(e) => handleToggle(e.target.checked)} className="odc-checkbox" />
          Include windows in this door
        </label>

        {includeCommWindows && (
          <>
            {/* Window Type */}
            <h3 className="odc-subsection-title">Window Type</h3>

            {thermopaneOptions.length > 0 && (
              <>
                <p style={{fontSize: '12px', color: 'var(--odc-text-muted)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600}}>Thermopane</p>
                <div className="odc-option-cards" style={{marginBottom: '16px'}}>
                  {thermopaneOptions.map((winId) => {
                    const winInfo = cwd[winId]
                    return (
                      <button key={winId}
                        className={`odc-option-card ${config.windowInsert === winId ? 'odc-selected' : ''}`}
                        onClick={() => onSelect(winId, recommended, config.glassColor || 'CLEAR', config.windowSection || defaultSection)}>
                        <strong>{winInfo.name}</strong>
                        <span className="odc-option-desc">24" section</span>
                      </button>
                    )
                  })}
                </div>
              </>
            )}

            {fullViewOptions.length > 0 && (
              <>
                <p style={{fontSize: '12px', color: 'var(--odc-text-muted)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600}}>Full View</p>
                <div className="odc-option-cards" style={{marginBottom: '20px'}}>
                  {fullViewOptions.map((winId) => {
                    const winInfo = cwd[winId]
                    return (
                      <button key={winId}
                        className={`odc-option-card ${config.windowInsert === winId ? 'odc-selected' : ''}`}
                        onClick={() => onSelect(winId, 1, config.glassColor || 'CLEAR', config.windowSection || defaultSection)}>
                        <strong>{winInfo.name}</strong>
                        <span className="odc-option-desc">Replaces insulated section</span>
                      </button>
                    )
                  })}
                </div>
              </>
            )}

            {hasSelection && (
              <>
                {/* Window Quantity with +/- and recommended */}
                <h3 className="odc-subsection-title">
                  {isFullView ? 'Number of Full View Sections' : 'Window Quantity'}
                </h3>
                <div style={{background: 'var(--odc-surface)', border: '1px solid var(--odc-border)', borderRadius: 'var(--odc-radius)', padding: '16px', marginBottom: '20px'}}>
                  <div style={{display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px'}}>
                    <button className="odc-size-btn" style={{width: 40, height: 40, minWidth: 40, padding: 0}}
                      onClick={() => onSelect(config.windowInsert, Math.max(1, currentQty - 1), config.glassColor, config.windowSection || defaultSection)}>
                      -
                    </button>
                    <span style={{fontSize: '20px', fontWeight: 700, minWidth: '40px', textAlign: 'center'}}>{currentQty}</span>
                    <button className="odc-size-btn" style={{width: 40, height: 40, minWidth: 40, padding: 0}}
                      onClick={() => onSelect(config.windowInsert, currentQty + 1, config.glassColor, config.windowSection || defaultSection)}>
                      +
                    </button>
                    <button className="odc-btn-primary" style={{padding: '8px 16px', fontSize: '13px'}}
                      onClick={() => onSelect(config.windowInsert, recommended, config.glassColor, config.windowSection || defaultSection)}>
                      Use Recommended ({recommended})
                    </button>
                  </div>
                  {spacing && (
                    <p style={{fontSize: '12px', color: 'var(--odc-accent)'}}>Spacing between windows: {spacing}"</p>
                  )}
                </div>

                {/* Window Section (which panel) */}
                <h3 className="odc-subsection-title">Window Section <span style={{fontSize: '13px', fontWeight: 400, color: 'var(--odc-text-secondary)'}}>(1 = Top)</span></h3>
                <div className="odc-size-presets">
                  {Array.from({ length: panelCount }).map((_, i) => (
                    <button key={i + 1}
                      className={`odc-size-btn ${(config.windowSection || defaultSection) === i + 1 ? 'odc-selected' : ''}`}
                      onClick={() => onSelect(config.windowInsert, config.windowQty, config.glassColor, i + 1)}>
                      {i + 1}
                    </button>
                  ))}
                </div>
                <p style={{fontSize: '12px', color: 'var(--odc-text-muted)', marginTop: '8px', marginBottom: '20px'}}>
                  This door has {panelCount} panels. Select which panel to place the {currentQty} window{currentQty !== 1 ? 's' : ''} in.
                </p>

                {/* Frame Color */}
                <h3 className="odc-subsection-title">Frame Color</h3>
                <p style={{fontSize: '12px', color: 'var(--odc-text-muted)', marginBottom: '12px'}}>Standard is black. Inside frame is always white.</p>
                <div className="odc-option-cards">
                  {[
                    { id: 'BLACK', name: 'Black Frame', hex: '#1a1a1a', desc: 'Black outside, white inside', std: true },
                    { id: 'WHITE', name: 'White Frame', hex: '#FFFFFF', desc: 'White outside, white inside', std: false },
                  ].map((fc) => (
                    <button key={fc.id}
                      className={`odc-option-card ${(config.windowFrameColor || 'BLACK') === fc.id ? 'odc-selected' : ''}`}
                      onClick={() => onSelect(config.windowInsert, config.windowQty, config.glassColor, config.windowSection || defaultSection, config.glassPaneType, fc.id)}
                      style={{display: 'flex', alignItems: 'center', gap: '12px'}}>
                      <div style={{width: 32, height: 32, borderRadius: '50%', backgroundColor: fc.hex, border: '2px solid var(--odc-border)', flexShrink: 0}} />
                      <div style={{textAlign: 'left'}}>
                        <strong>{fc.name}{fc.std ? ' (Standard)' : ''}</strong>
                        <span className="odc-option-desc">{fc.desc}</span>
                      </div>
                    </button>
                  ))}
                </div>

                {/* Glass Type */}
                <h3 className="odc-subsection-title">Glass Type</h3>
                <div className="odc-option-cards">
                  {[
                    { id: 'CLEAR', name: 'Clear Glass' },
                    { id: 'INSULATED', name: 'Insulated Glass' },
                    { id: 'ETCHED', name: 'Etched Glass' },
                    { id: 'TEMPERED', name: 'Tempered Glass' },
                  ].map((g) => (
                    <button key={g.id}
                      className={`odc-option-card ${config.glassColor === g.id ? 'odc-selected' : ''}`}
                      onClick={() => onSelect(config.windowInsert, config.windowQty, g.id, config.windowSection || defaultSection, config.glassPaneType, config.windowFrameColor)}>
                      <strong>{g.name}</strong>
                    </button>
                  ))}
                </div>
              </>
            )}
          </>
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
