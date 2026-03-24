import React from 'react'
import DoorPreview from '../DoorPreview'

export default function WindowStep({ options, family, config, onSelect }) {
  const windowInserts = family?.windowInserts || []

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
      <p className="odc-step-subtitle">Add decorative window inserts to your top section</p>
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
              onClick={() => onSelect(windowId)}
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
    </div>
  )
}
