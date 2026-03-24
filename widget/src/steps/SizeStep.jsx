import React, { useState, useEffect } from 'react'

export default function SizeStep({ options, family, config, onSelect }) {
  // Use family-specific sizes if available (e.g. "craft"), then door type, then residential fallback
  const familyId = family?.id || ''
  const doorType = family?.type === 'commercial' ? 'commercial' : 'residential'
  const sizeConfig = options.sizes[familyId] || options.sizes[doorType] || options.sizes.residential
  const allowCustom = sizeConfig.customSizeAllowed !== false

  // Convert inches to feet + inches for display
  const toFeetInches = (inches) => {
    const ft = Math.floor(inches / 12)
    const inc = inches % 12
    return { ft, inc }
  }

  const widthFI = toFeetInches(config.width)
  const heightFI = toFeetInches(config.height)

  const [customWidth, setCustomWidth] = useState(false)
  const [customHeight, setCustomHeight] = useState(false)
  const [customWidthFt, setCustomWidthFt] = useState(String(widthFI.ft))
  const [customWidthIn, setCustomWidthIn] = useState(String(widthFI.inc))
  const [customHeightFt, setCustomHeightFt] = useState(String(heightFI.ft))
  const [customHeightIn, setCustomHeightIn] = useState(String(heightFI.inc))

  // Check if current value matches a preset
  const widthFeet = config.width / 12
  const heightFeet = config.height / 12
  const isPresetWidth = sizeConfig.widths.includes(widthFeet) && config.width % 12 === 0
  const isPresetHeight = sizeConfig.heights.includes(heightFeet) && config.height % 12 === 0

  useEffect(() => {
    if (!isPresetWidth) setCustomWidth(true)
    if (!isPresetHeight) setCustomHeight(true)
  }, [])

  const handleWidthPreset = (ft) => {
    setCustomWidth(false)
    onSelect(ft * 12, config.height)
  }

  const handleHeightPreset = (ft) => {
    setCustomHeight(false)
    onSelect(config.width, ft * 12)
  }

  const handleCustomWidthApply = () => {
    const ft = parseInt(customWidthFt) || 0
    const inc = parseInt(customWidthIn) || 0
    const totalInches = ft * 12 + inc
    if (totalInches > 0) {
      onSelect(totalInches, config.height)
    }
  }

  const handleCustomHeightApply = () => {
    const ft = parseInt(customHeightFt) || 0
    const inc = parseInt(customHeightIn) || 0
    const totalInches = ft * 12 + inc
    if (totalInches > 0) {
      onSelect(config.width, totalInches)
    }
  }

  return (
    <div className="odc-step-content">
      <h2 className="odc-step-title">Choose Your Size</h2>
      <p className="odc-step-subtitle">Select the width and height for your {family?.name}</p>

      {/* Width Selection */}
      <div className="odc-size-section">
        <h3 className="odc-size-label">Width</h3>
        <div className="odc-size-presets">
          {sizeConfig.widths.map((ft) => (
            <button
              key={`w-${ft}`}
              className={`odc-size-btn ${!customWidth && config.width === ft * 12 ? 'odc-selected' : ''}`}
              onClick={() => handleWidthPreset(ft)}
            >
              {ft}'
            </button>
          ))}
          {allowCustom && (
            <button
              className={`odc-size-btn odc-size-custom-toggle ${customWidth ? 'odc-selected' : ''}`}
              onClick={() => setCustomWidth(true)}
            >
              Custom
            </button>
          )}
        </div>
        {allowCustom && customWidth && (
          <div className="odc-size-custom-input">
            <div className="odc-size-field-group">
              <input
                type="number"
                className="odc-size-input"
                value={customWidthFt}
                onChange={(e) => setCustomWidthFt(e.target.value)}
                onBlur={handleCustomWidthApply}
                min="4"
                max="30"
                placeholder="0"
              />
              <span className="odc-size-unit">ft</span>
              <input
                type="number"
                className="odc-size-input"
                value={customWidthIn}
                onChange={(e) => setCustomWidthIn(e.target.value)}
                onBlur={handleCustomWidthApply}
                min="0"
                max="11"
                placeholder="0"
              />
              <span className="odc-size-unit">in</span>
            </div>
          </div>
        )}
      </div>

      {/* Height Selection */}
      <div className="odc-size-section">
        <h3 className="odc-size-label">Height</h3>
        <div className="odc-size-presets">
          {sizeConfig.heights.map((ft) => (
            <button
              key={`h-${ft}`}
              className={`odc-size-btn ${!customHeight && config.height === ft * 12 ? 'odc-selected' : ''}`}
              onClick={() => handleHeightPreset(ft)}
            >
              {ft}'
            </button>
          ))}
          {allowCustom && (
            <button
              className={`odc-size-btn odc-size-custom-toggle ${customHeight ? 'odc-selected' : ''}`}
              onClick={() => setCustomHeight(true)}
            >
              Custom
            </button>
          )}
        </div>
        {allowCustom && customHeight && (
          <div className="odc-size-custom-input">
            <div className="odc-size-field-group">
              <input
                type="number"
                className="odc-size-input"
                value={customHeightFt}
                onChange={(e) => setCustomHeightFt(e.target.value)}
                onBlur={handleCustomHeightApply}
                min="4"
                max="20"
                placeholder="0"
              />
              <span className="odc-size-unit">ft</span>
              <input
                type="number"
                className="odc-size-input"
                value={customHeightIn}
                onChange={(e) => setCustomHeightIn(e.target.value)}
                onBlur={handleCustomHeightApply}
                min="0"
                max="11"
                placeholder="0"
              />
              <span className="odc-size-unit">in</span>
            </div>
          </div>
        )}
      </div>

      {/* Current size display */}
      <div className="odc-size-display">
        <span className="odc-size-display-label">Selected Size</span>
        <span className="odc-size-display-value">
          {widthFI.inc > 0 ? `${widthFI.ft}'-${widthFI.inc}"` : `${widthFI.ft}'-0"`}
          {' x '}
          {heightFI.inc > 0 ? `${heightFI.ft}'-${heightFI.inc}"` : `${heightFI.ft}'-0"`}
        </span>
      </div>
    </div>
  )
}
