import React, { useState, useCallback } from 'react'
import DoorPreview from './DoorPreview'
import StyleStep from './steps/StyleStep'
import SizeStep from './steps/SizeStep'
import DesignStep from './steps/DesignStep'
import ColorStep from './steps/ColorStep'
import WindowStep from './steps/WindowStep'
import SummaryStep from './steps/SummaryStep'

const STEPS = [
  { id: 'style', label: 'Style' },
  { id: 'size', label: 'Size' },
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
    windowPositions: [],
    windowSize: 'long',
    windowQty: 0,
    glassPaneType: null,
    glassColor: 'CLEAR',
    windowSection: 1,
    width: 192, // 16' in inches
    height: 96, // 8' in inches
  })

  const goTo = useCallback((s) => setStep(Math.max(0, Math.min(s, STEPS.length - 1))), [])
  const next = useCallback(() => setStep(s => Math.min(s + 1, STEPS.length - 1)), [])
  const prev = useCallback(() => setStep(s => Math.max(s - 1, 0)), [])

  const handleFamilySelect = useCallback((f) => {
    setFamily(f)
    // Determine default size based on door type
    const sizeConfig = options.sizes[f.type === 'commercial' ? 'commercial' : 'residential'] || options.sizes.residential
    const defaultWidth = (sizeConfig.defaultWidth || 16) * 12
    const defaultHeight = (sizeConfig.defaultHeight || 8) * 12
    const newConfig = {
      ...config,
      color: f.defaultColor || 'WHITE',
      panelDesign: f.defaultDesign || f.designs?.[0] || 'FLUSH',
      doorType: f.type,
      doorSeries: f.series === 'CRAFT' ? 'CRAFT' : (f.type === 'aluminium' ? 'AL976' : ''),
      windowInsert: null,
      windowPositions: [],
      windowSize: 'long',
      windowQty: 0,
      glassPaneType: null,
      glassColor: 'CLEAR',
      windowSection: 1,
      width: defaultWidth,
      height: defaultHeight,
    }
    setConfig(newConfig)
    next()
  }, [config, next, options])

  const handleSizeSelect = useCallback((w, h) => {
    setConfig(c => ({ ...c, width: w, height: h }))
  }, [])

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

  const handleWindowSelect = useCallback((windowId, qty, glassType, section) => {
    setConfig(c => {
      const updates = {}
      if (windowId !== undefined) {
        const newInsert = windowId === 'NONE' ? null : windowId
        updates.windowInsert = newInsert
        // Reset positions when insert type changes
        if (newInsert !== c.windowInsert) {
          updates.windowPositions = []
        }
        // Derive windowSize from options windowData
        if (newInsert && options.windowData?.[newInsert]) {
          updates.windowSize = options.windowData[newInsert].size || 'long'
        } else {
          updates.windowSize = 'long'
        }
      }
      if (qty !== undefined) {
        updates.windowQty = qty
      }
      if (glassType !== undefined) {
        updates.glassPaneType = glassType
        updates.glassColor = glassType
      }
      if (section !== undefined) {
        updates.windowSection = section
      }
      return { ...c, ...updates }
    })
  }, [options])

  const handleWindowPositionsChange = useCallback((positions) => {
    setConfig(c => ({ ...c, windowPositions: positions }))
  }, [])

  // Determine skip logic
  const isCommercial = family?.type === 'commercial'
  const hasCommercialWindows = isCommercial && family?.commercialWindows?.length > 0
  const shouldSkipWindows = family && (family.windowInserts?.length === 0) && !hasCommercialWindows
  const shouldSkipDesign = family && (!family.designs || family.designs.length === 0)

  const handleNext = useCallback(() => {
    let nextStep = step + 1
    // Skip design for AL976 (step 2)
    if (nextStep === 2 && shouldSkipDesign) {
      nextStep = 3
    }
    // Skip windows for Craft (step 4) — but NOT for commercial
    if (nextStep === 4 && shouldSkipWindows) {
      nextStep = 5
    }
    setStep(Math.min(nextStep, STEPS.length - 1))
  }, [step, shouldSkipDesign, shouldSkipWindows])

  const handlePrev = useCallback(() => {
    let prevStep = step - 1
    // Skip windows going back
    if (prevStep === 4 && shouldSkipWindows) {
      prevStep = 3
    }
    // Skip design going back for AL976
    if (prevStep === 2 && shouldSkipDesign) {
      prevStep = 1
    }
    setStep(Math.max(prevStep, 0))
  }, [step, shouldSkipDesign, shouldSkipWindows])

  // Show live preview alongside steps (not on style or summary)
  const showSidePreview = step > 0 && step < 5

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
            <SizeStep options={options} family={family} config={config} onSelect={handleSizeSelect} />
          )}
          {step === 2 && (
            <DesignStep options={options} family={family} config={config} onSelect={handleDesignSelect} />
          )}
          {step === 3 && (
            <ColorStep options={options} family={family} config={config} onSelect={handleColorSelect} />
          )}
          {step === 4 && (
            <WindowStep options={options} family={family} config={config} onSelect={handleWindowSelect} onWindowPositionsChange={handleWindowPositionsChange} />
          )}
          {step === 5 && (
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
                windowPositions={config.windowPositions || []}
                windowSection={config.windowSection || 1}
                windowSize={config.windowSize || 'long'}
                windowQty={config.windowQty || 0}
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
