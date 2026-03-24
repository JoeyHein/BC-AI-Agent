import React from 'react'

export default function ColorStep({ options, family, config, onSelect }) {
  const colors = family?.colors || []

  // For AL976, also handle glass options
  const isAluminium = family?.type === 'aluminium'
  const glassOptions = family?.glassOptions || []

  return (
    <div className="odc-step-content">
      <h2 className="odc-step-title">Choose Your {isAluminium ? 'Finish' : 'Color'}</h2>
      <p className="odc-step-subtitle">Select a {isAluminium ? 'frame finish' : 'color'} for your {family?.name}</p>
      <div className="odc-color-grid">
        {colors.map((colorId) => {
          const colorInfo = options.colorData[colorId]
          if (!colorInfo) return null
          const isSelected = config.color === colorId
          const isWoodgrain = colorInfo.type === 'woodgrain'
          return (
            <button
              key={colorId}
              className={`odc-color-swatch ${isSelected ? 'odc-selected' : ''}`}
              onClick={() => onSelect(colorId)}
              title={colorInfo.name}
            >
              <div className="odc-color-circle-wrap">
                {isWoodgrain ? (
                  <div className="odc-color-circle odc-woodgrain" style={{
                    background: `linear-gradient(135deg, ${colorInfo.light || colorInfo.hex} 0%, ${colorInfo.hex} 40%, ${colorInfo.dark || colorInfo.hex} 100%)`
                  }} />
                ) : (
                  <div className="odc-color-circle" style={{ backgroundColor: colorInfo.hex }} />
                )}
              </div>
              <span className="odc-color-name">{colorInfo.name}</span>
              {isWoodgrain && <span className="odc-color-type">Woodgrain</span>}
            </button>
          )
        })}
      </div>

      {isAluminium && glassOptions.length > 0 && (
        <>
          <h3 className="odc-subsection-title">Glass Type</h3>
          <div className="odc-color-grid">
            {glassOptions.map((glassId) => {
              const glassInfo = options.glassData?.[glassId]
              if (!glassInfo) return null
              const isSelected = config.glassColor === glassId
              const glassColors = { CLEAR: '#A8D8EA', ETCHED: '#D3D3D3', SUPER_GREY: '#4A4A4A' }
              return (
                <button
                  key={glassId}
                  className={`odc-color-swatch ${isSelected ? 'odc-selected' : ''}`}
                  onClick={() => onSelect(null, glassId)}
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
