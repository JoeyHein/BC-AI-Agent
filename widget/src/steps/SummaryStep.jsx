import React, { useState, useRef, useCallback } from 'react'
import DoorPreview from '../DoorPreview'

export default function SummaryStep({ options, family, config, quoteWebhook, dealerLocatorUrl }) {
  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState({ name: '', email: '', phone: '', postalCode: '', notes: '' })
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const previewRef = useRef(null)

  // Capture SVG as PNG data URL
  const captureDoorImage = useCallback(() => {
    return new Promise((resolve) => {
      try {
        const svgEl = previewRef.current?.querySelector('svg')
        if (!svgEl) { resolve(null); return }
        const svgData = new XMLSerializer().serializeToString(svgEl)
        const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' })
        const url = URL.createObjectURL(svgBlob)
        const img = new Image()
        img.onload = () => {
          const canvas = document.createElement('canvas')
          canvas.width = img.naturalWidth * 2
          canvas.height = img.naturalHeight * 2
          const ctx = canvas.getContext('2d')
          ctx.scale(2, 2)
          ctx.drawImage(img, 0, 0)
          URL.revokeObjectURL(url)
          resolve(canvas.toDataURL('image/png'))
        }
        img.onerror = () => { URL.revokeObjectURL(url); resolve(null) }
        img.src = url
      } catch { resolve(null) }
    })
  }, [])

  const designInfo = options.designData[config.panelDesign]
  const colorInfo = options.colorData[config.color]
  const windowInfo = config.windowInsert ? options.windowData[config.windowInsert] : null
  const commercialWindowInfo = config.windowInsert ? options.commercialWindowData?.[config.windowInsert] : null
  const glassInfo = config.glassColor ? options.glassData?.[config.glassColor] : null

  // Determine if windows are actually present (positions placed or commercial qty > 0)
  const isCommercial = family?.type === 'commercial'
  const hasWindows = config.windowInsert && config.windowInsert !== 'NONE' && (
    (config.windowPositions?.length > 0) || (isCommercial && config.windowQty > 0)
  )

  // Format size display
  const formatSize = (inches) => {
    const ft = Math.floor(inches / 12)
    const inc = inches % 12
    return inc > 0 ? `${ft}'-${inc}"` : `${ft}'-0"`
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      // Capture the door preview image
      const doorImage = await captureDoorImage()

      const doorConfig = {
        family: family?.name,
        familyId: family?.id,
        size: `${formatSize(config.width)} x ${formatSize(config.height)}`,
        widthInches: config.width,
        heightInches: config.height,
        design: designInfo?.name || 'N/A',
        designId: config.panelDesign,
        color: colorInfo?.name,
        colorId: config.color,
        windows: hasWindows ? (commercialWindowInfo?.name || windowInfo?.name || 'None') : 'None',
        windowId: hasWindows ? (config.windowInsert || 'NONE') : 'NONE',
        windowPositions: config.windowPositions || [],
        windowSize: config.windowSize || 'long',
        windowQty: config.windowQty || 0,
        glassType: hasWindows ? (glassInfo?.name || null) : null,
        glassId: hasWindows ? (config.glassColor || null) : null,
        windowFrameColor: config.windowFrameColor || 'MATCH',
      }
      const payload = {
        contact: formData,
        doorConfig,
        doorImage,
        timestamp: new Date().toISOString(),
      }

      if (quoteWebhook) {
        await fetch(quoteWebhook, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
      }
      setSubmitted(true)
    } catch (err) {
      console.error('Quote submission error:', err)
      setSubmitted(true) // Still show success to user
    }
    setSubmitting(false)
  }

  const handleChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }))
  }

  if (submitted) {
    return (
      <div className="odc-step-content odc-summary">
        <div className="odc-success-message">
          <div className="odc-success-icon">&#10003;</div>
          <h2 className="odc-step-title">Quote Request Sent!</h2>
          <p className="odc-step-subtitle">
            Thank you, {formData.name}. A dealer in your area will contact you shortly with pricing for your custom door configuration.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="odc-step-content odc-summary">
      <h2 className="odc-step-title">Your Custom Door</h2>
      <p className="odc-step-subtitle">Review your configuration</p>

      <div className="odc-summary-layout">
        <div className="odc-summary-preview" ref={previewRef}>
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
            maxWidth={380}
          />
        </div>

        <div className="odc-summary-details">
          <div className="odc-detail-row">
            <span className="odc-detail-label">Collection</span>
            <span className="odc-detail-value">{family?.name}</span>
          </div>
          <div className="odc-detail-row">
            <span className="odc-detail-label">Size</span>
            <span className="odc-detail-value">{formatSize(config.width)} x {formatSize(config.height)}</span>
          </div>
          {designInfo && (
            <div className="odc-detail-row">
              <span className="odc-detail-label">Design</span>
              <span className="odc-detail-value">{designInfo.name}</span>
            </div>
          )}
          <div className="odc-detail-row">
            <span className="odc-detail-label">Color</span>
            <span className="odc-detail-value">
              <span className="odc-detail-color-dot" style={{ backgroundColor: colorInfo?.hex }} />
              {colorInfo?.name}
            </span>
          </div>
          {commercialWindowInfo && config.windowInsert !== 'NONE' && config.windowQty > 0 && (
            <div className="odc-detail-row">
              <span className="odc-detail-label">Windows</span>
              <span className="odc-detail-value">
                {commercialWindowInfo.name} (x{config.windowQty})
              </span>
            </div>
          )}
          {windowInfo && !commercialWindowInfo && config.windowInsert && config.windowInsert !== 'NONE' && config.windowPositions?.length > 0 && (
            <div className="odc-detail-row">
              <span className="odc-detail-label">Windows</span>
              <span className="odc-detail-value">
                {windowInfo.name} ({config.windowPositions.length} placed)
              </span>
            </div>
          )}
          {glassInfo && config.glassColor && hasWindows && (
            <div className="odc-detail-row">
              <span className="odc-detail-label">Glass</span>
              <span className="odc-detail-value">{glassInfo.name}</span>
            </div>
          )}

          <div className="odc-cta-group">
            <button className="odc-btn-primary" onClick={() => setShowForm(true)}>
              Request a Quote
            </button>
            {dealerLocatorUrl && (
              <a href={dealerLocatorUrl} target="_blank" rel="noopener noreferrer" className="odc-btn-outline">
                Find a Dealer
              </a>
            )}
          </div>
        </div>
      </div>

      {showForm && (
        <div className="odc-modal-overlay" onClick={() => setShowForm(false)}>
          <div className="odc-modal" onClick={(e) => e.stopPropagation()}>
            <button className="odc-modal-close" onClick={() => setShowForm(false)}>&times;</button>
            <h3 className="odc-modal-title">Request a Quote</h3>
            <p className="odc-modal-subtitle">A local dealer will contact you with pricing for your custom {family?.name} door.</p>
            <form onSubmit={handleSubmit} className="odc-quote-form">
              <div className="odc-form-row">
                <label className="odc-form-label">Full Name *</label>
                <input type="text" required className="odc-form-input"
                  value={formData.name} onChange={(e) => handleChange('name', e.target.value)} />
              </div>
              <div className="odc-form-row">
                <label className="odc-form-label">Email *</label>
                <input type="email" required className="odc-form-input"
                  value={formData.email} onChange={(e) => handleChange('email', e.target.value)} />
              </div>
              <div className="odc-form-row-double">
                <div className="odc-form-row">
                  <label className="odc-form-label">Phone</label>
                  <input type="tel" className="odc-form-input"
                    value={formData.phone} onChange={(e) => handleChange('phone', e.target.value)} />
                </div>
                <div className="odc-form-row">
                  <label className="odc-form-label">Postal Code</label>
                  <input type="text" className="odc-form-input"
                    value={formData.postalCode} onChange={(e) => handleChange('postalCode', e.target.value)} />
                </div>
              </div>
              <div className="odc-form-row">
                <label className="odc-form-label">Notes</label>
                <textarea className="odc-form-textarea" rows="3"
                  placeholder="Any additional details about your project..."
                  value={formData.notes} onChange={(e) => handleChange('notes', e.target.value)} />
              </div>
              <button type="submit" className="odc-btn-primary odc-btn-full" disabled={submitting}>
                {submitting ? 'Sending...' : 'Submit Quote Request'}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
