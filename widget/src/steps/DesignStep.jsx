import React from 'react'
import DoorPreview from '../DoorPreview'

export default function DesignStep({ options, family, config, onSelect }) {
  if (!family || !family.designs || family.designs.length === 0) {
    return (
      <div className="odc-step-content">
        <h2 className="odc-step-title">Panel Design</h2>
        <p className="odc-step-subtitle">No panel designs available for this collection. Continue to the next step.</p>
      </div>
    )
  }

  return (
    <div className="odc-step-content">
      <h2 className="odc-step-title">Choose Your Design</h2>
      <p className="odc-step-subtitle">Select a panel pattern for your {family.name}</p>
      <div className="odc-design-grid">
        {family.designs.map((designId) => {
          const design = options.designData[designId]
          if (!design) return null
          return (
            <button
              key={designId}
              className={`odc-design-card ${config.panelDesign === designId ? 'odc-selected' : ''}`}
              onClick={() => onSelect(designId)}
            >
              <div className="odc-design-preview">
                <DoorPreview
                  width={config.width}
                  height={config.height}
                  color={config.color}
                  panelDesign={designId}
                  doorType={config.doorType}
                  doorSeries={config.doorSeries}
                  showDimensions={false}
                  maxWidth={140}
                />
              </div>
              <div className="odc-design-info">
                <span className="odc-design-name">{design.name}</span>
                <span className="odc-design-desc">{design.description}</span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
