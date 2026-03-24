import React from 'react'
import DoorPreview from '../DoorPreview'

const FAMILY_DEFAULTS = {
  kanata: { panelDesign: 'SHXL', color: 'WHITE', doorType: 'residential', doorSeries: '', width: 192, height: 96 },
  craft: { panelDesign: 'MUSKOKA', color: 'WALNUT', doorType: 'residential', doorSeries: 'CRAFT', width: 192, height: 96 },
  al976: { panelDesign: 'FLUSH', color: 'BLACK_ANODIZED', doorType: 'aluminium', doorSeries: 'AL976', width: 192, height: 96 },
}

export default function StyleStep({ options, onSelect }) {
  return (
    <div className="odc-step-content">
      <h2 className="odc-step-title">Choose Your Style</h2>
      <p className="odc-step-subtitle">Select a door collection to get started</p>
      <div className="odc-family-grid">
        {options.doorFamilies.map((family) => {
          const defaults = FAMILY_DEFAULTS[family.id] || FAMILY_DEFAULTS.kanata
          return (
            <button
              key={family.id}
              className="odc-family-card"
              onClick={() => onSelect(family)}
            >
              <div className="odc-family-preview">
                <DoorPreview
                  width={defaults.width}
                  height={defaults.height}
                  color={defaults.color}
                  panelDesign={defaults.panelDesign}
                  doorType={defaults.doorType}
                  doorSeries={defaults.doorSeries}
                  glassColor="CLEAR"
                  showDimensions={false}
                  maxWidth={220}
                />
              </div>
              <div className="odc-family-info">
                <h3 className="odc-family-name">{family.name}</h3>
                <span className="odc-family-tagline">{family.tagline}</span>
                <p className="odc-family-desc">{family.description}</p>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
