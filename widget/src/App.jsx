import React, { useState, useCallback } from 'react'
import DoorPreview from './DoorPreview'
import StyleStep from './steps/StyleStep'
import DesignStep from './steps/DesignStep'
import ColorStep from './steps/ColorStep'
import WindowStep from './steps/WindowStep'
import SummaryStep from './steps/SummaryStep'

const STEPS = [
  { id: 'style', label: 'Style' },
  { id: 'design', label: 'Design' },
  { id: 'color', label: 'Color' },
  { id: 'windows', label: 'Windows' },
  { id: 'summary', label: 'Summary' },
]

export default function App({ options, quoteWebhook, dealerLocatorUrl }) {
  const [step, setStep] = useState(0)
  const [family, setFamily] = useState(null)
  const [config, setConfig] = useState({
    color: 'WHITE',
    panelDesign: 'SHXL',
    doorType: 'residential',
    doorSeries: '',
    windowInsert: null,
    glassColor: 'CLEAR',
    width: 192, // 16' in inches
    height: 96, // 8' in inches
  })

  const goTo = useCallback((s) => setStep(Math.max(0, Math.min(s, STEPS.length - 1))), [])
  const next = useCallback(() => setStep(s => Math.min(s + 1, STEPS.length - 1)), [])
  const prev = useCallback(() => setStep(s => Math.max(s - 1, 0)), [])

  const handleFamilySelect = useCallback((f) => {
    setFamily(f)
    const newConfig = {
      ...config,
      color: f.defaultColor || 'WHITE',
      panelDesign: f.defaultDesign || f.designs?.[0] || 'FLUSH',
      doorType: f.type,
      doorSeries: f.series === 'CRAFT' ? 'CRAFT' : (f.type === 'aluminium' ? 'AL976' : ''),
      windowInsert: null,
      glassColor: 'CLEAR',
    }
    setConfig(newConfig)
    // Skip design step if no designs (AL976)
    if (!f.designs || f.designs.length === 0) {
      setStep(2) // go to color
    } else {
      next()
    }
  }, [config, next])

  const handleDesignSelect = useCallback((designId) => {
    setConfig(c => ({ ...c, panelDesign: designId }))
  }, [])

  const handleColorSelect = useCallback((colorId, glassId) => {
    if (glassId) {
      setConfig(c => ({ ...c, glassColor: glassId }))
    } else if (colorId) {
      setConfig(c => ({ ...c, color: colorId }))
    }
  }, [])

  const handleWindowSelect = useCallback((windowId) => {
    setConfig(c => ({ ...c, windowInsert: windowId === 'NONE' ? null : windowId }))
  }, [])

  // Determine if current step should be skipped
  const shouldSkipWindows = family && (family.windowInserts?.length === 0)

  const handleNext = useCallback(() => {
    const nextStep = step + 1
    // Skip windows for Craft/AL976
    if (nextStep === 3 && shouldSkipWindows) {
      setStep(4)
    } else {
      next()
    }
  }, [step, shouldSkipWindows, next])

  const handlePrev = useCallback(() => {
    const prevStep = step - 1
    // Skip windows going back
    if (prevStep === 3 && shouldSkipWindows) {
      setStep(2)
    // Skip design going back for AL976
    } else if (prevStep === 1 && family && (!family.designs || family.designs.length === 0)) {
      setStep(0)
    } else {
      prev()
    }
  }, [step, shouldSkipWindows, family, prev])

  // Show live preview alongside steps (not on style or summary)
  const showSidePreview = step > 0 && step < 4

  return (
    <div className="odc-widget">
      {/* Progress bar */}
      <div className="odc-progress">
        {STEPS.map((s, i) => (
          <button
            key={s.id}
            className={`odc-progress-step ${i === step ? 'odc-active' : ''} ${i < step ? 'odc-done' : ''}`}
            onClick={() => i < step && goTo(i)}
            disabled={i > step}
          >
            <span className="odc-progress-num">{i < step ? '\u2713' : i + 1}</span>
            <span className="odc-progress-label">{s.label}</span>
          </button>
        ))}
        <div className="odc-progress-bar">
          <div className="odc-progress-fill" style={{ width: `${(step / (STEPS.length - 1)) * 100}%` }} />
        </div>
      </div>

      {/* Main content area */}
      <div className={`odc-main ${showSidePreview ? 'odc-with-preview' : ''}`}>
        {/* Step content */}
        <div className="odc-step-panel">
          {step === 0 && (
            <StyleStep options={options} onSelect={handleFamilySelect} />
          )}
          {step === 1 && (
            <DesignStep options={options} family={family} config={config} onSelect={handleDesignSelect} />
          )}
          {step === 2 && (
            <ColorStep options={options} family={family} config={config} onSelect={handleColorSelect} />
          )}
          {step === 3 && (
            <WindowStep options={options} family={family} config={config} onSelect={handleWindowSelect} />
          )}
          {step === 4 && (
            <SummaryStep
              options={options}
              family={family}
              config={config}
              quoteWebhook={quoteWebhook}
              dealerLocatorUrl={dealerLocatorUrl}
            />
          )}
        </div>

        {/* Live preview sidebar */}
        {showSidePreview && (
          <div className="odc-preview-panel">
            <div className="odc-preview-sticky">
              <DoorPreview
                width={config.width}
                height={config.height}
                color={config.color}
                panelDesign={config.panelDesign}
                doorType={config.doorType}
                doorSeries={config.doorSeries}
                windowInsert={config.windowInsert}
                windowSection={1}
                hasInserts={true}
                glassColor={config.glassColor || 'CLEAR'}
                showDimensions={true}
                maxWidth={340}
              />
            </div>
          </div>
        )}
      </div>

      {/* Navigation */}
      {step > 0 && (
        <div className="odc-nav">
          <button className="odc-btn-outline" onClick={handlePrev}>Back</button>
          {step < STEPS.length - 1 && (
            <button className="odc-btn-primary" onClick={handleNext}>Continue</button>
          )}
        </div>
      )}
    </div>
  )
}
