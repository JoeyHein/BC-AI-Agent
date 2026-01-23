/**
 * WindowSelector Component
 * Displays available window options for click-to-add functionality
 * Shows windows appropriate for the current door design/series
 */

import { useMemo } from 'react'
import {
  getWindowsForDesign,
  GLASS_STYLES,
} from '../config/windowSpecifications'

function WindowSelector({
  panelDesign = 'SH',
  doorType = 'residential',
  selectedWindow = null,
  selectedGlassStyle = 'PLAIN',
  onWindowSelect,
  onGlassStyleSelect,
  onClear,
  // For commercial doors - frame color option
  frameColor = 'WHITE',
  onFrameColorChange,
}) {
  // Get available windows for this door design
  const availableWindows = useMemo(() => {
    return Object.values(getWindowsForDesign(panelDesign))
  }, [panelDesign])

  const isCommercial = doorType === 'commercial'

  return (
    <div className="window-selector" style={styles.container}>
      <h3 style={styles.title}>Window Options</h3>

      {/* Window Size Selection */}
      <div style={styles.section}>
        <label style={styles.label}>Window Size</label>
        <div style={styles.windowGrid}>
          {availableWindows.map((window) => (
            <button
              key={window.id}
              onClick={() => onWindowSelect(window.id === selectedWindow ? null : window.id)}
              style={{
                ...styles.windowButton,
                ...(selectedWindow === window.id ? styles.windowButtonSelected : {}),
              }}
            >
              <div style={styles.windowName}>{window.name}</div>
              <div style={styles.windowSize}>
                {window.width}" × {window.height}"
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Glass Style Selection */}
      {selectedWindow && (
        <div style={styles.section}>
          <label style={styles.label}>Glass Style</label>
          <div style={styles.styleGrid}>
            {Object.values(GLASS_STYLES).map((style) => (
              <button
                key={style.id}
                onClick={() => onGlassStyleSelect(style.id)}
                style={{
                  ...styles.styleButton,
                  ...(selectedGlassStyle === style.id ? styles.styleButtonSelected : {}),
                }}
              >
                {style.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Frame Color for Commercial Doors */}
      {isCommercial && selectedWindow && (
        <div style={styles.section}>
          <label style={styles.label}>Frame Color</label>
          <div style={styles.frameColorGrid}>
            <button
              onClick={() => onFrameColorChange('WHITE')}
              style={{
                ...styles.frameColorButton,
                backgroundColor: '#FFFFFF',
                color: '#333',
                ...(frameColor === 'WHITE' ? styles.frameColorSelected : {}),
              }}
            >
              White
            </button>
            <button
              onClick={() => onFrameColorChange('BLACK')}
              style={{
                ...styles.frameColorButton,
                backgroundColor: '#1A1A1A',
                color: '#FFF',
                ...(frameColor === 'BLACK' ? styles.frameColorSelected : {}),
              }}
            >
              Black
            </button>
          </div>
        </div>
      )}

      {/* Instructions */}
      <div style={styles.instructions}>
        {selectedWindow ? (
          <p style={styles.instructionText}>
            Click on a door section to add this window.
            <br />
            Click an existing window to remove it.
          </p>
        ) : (
          <p style={styles.instructionText}>
            Select a window size above, then click on a door section to place it.
          </p>
        )}
      </div>

      {/* Clear All Button */}
      {onClear && (
        <button onClick={onClear} style={styles.clearButton}>
          Clear All Windows
        </button>
      )}
    </div>
  )
}

const styles = {
  container: {
    padding: '16px',
    backgroundColor: '#f8f9fa',
    borderRadius: '8px',
    border: '1px solid #e9ecef',
    maxWidth: '320px',
  },
  title: {
    margin: '0 0 16px 0',
    fontSize: '16px',
    fontWeight: '600',
    color: '#333',
  },
  section: {
    marginBottom: '16px',
  },
  label: {
    display: 'block',
    fontSize: '12px',
    fontWeight: '500',
    color: '#666',
    marginBottom: '8px',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  windowGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: '8px',
  },
  windowButton: {
    padding: '10px 8px',
    border: '2px solid #dee2e6',
    borderRadius: '6px',
    backgroundColor: '#fff',
    cursor: 'pointer',
    textAlign: 'center',
    transition: 'all 0.15s ease',
  },
  windowButtonSelected: {
    borderColor: '#3b82f6',
    backgroundColor: '#eff6ff',
  },
  windowName: {
    fontSize: '13px',
    fontWeight: '500',
    color: '#333',
    marginBottom: '2px',
  },
  windowSize: {
    fontSize: '11px',
    color: '#666',
  },
  styleGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: '6px',
  },
  styleButton: {
    padding: '8px 6px',
    border: '1px solid #dee2e6',
    borderRadius: '4px',
    backgroundColor: '#fff',
    cursor: 'pointer',
    fontSize: '12px',
    transition: 'all 0.15s ease',
  },
  styleButtonSelected: {
    borderColor: '#3b82f6',
    backgroundColor: '#eff6ff',
    fontWeight: '500',
  },
  frameColorGrid: {
    display: 'flex',
    gap: '8px',
  },
  frameColorButton: {
    flex: 1,
    padding: '10px',
    border: '2px solid #dee2e6',
    borderRadius: '6px',
    cursor: 'pointer',
    fontSize: '13px',
    fontWeight: '500',
    transition: 'all 0.15s ease',
  },
  frameColorSelected: {
    borderColor: '#3b82f6',
    boxShadow: '0 0 0 2px rgba(59, 130, 246, 0.3)',
  },
  instructions: {
    padding: '12px',
    backgroundColor: '#e7f3ff',
    borderRadius: '6px',
    marginBottom: '12px',
  },
  instructionText: {
    margin: 0,
    fontSize: '12px',
    color: '#1e40af',
    lineHeight: '1.5',
  },
  clearButton: {
    width: '100%',
    padding: '10px',
    border: 'none',
    borderRadius: '6px',
    backgroundColor: '#ef4444',
    color: '#fff',
    fontSize: '13px',
    fontWeight: '500',
    cursor: 'pointer',
    transition: 'background-color 0.15s ease',
  },
}

export default WindowSelector
