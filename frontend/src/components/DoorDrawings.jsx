/**
 * DoorDrawings Component
 * Combined view for door drawings with export functionality.
 *
 * Tabs:
 *  - Door Preview: in-browser SVG visualization of the door's appearance.
 *  - Shop Drawing: production CAD drawing rendered by the backend ezdxf
 *    pipeline. Always available via the "Produce Drawing" button — works
 *    before the quote is saved (uses the preview endpoint with the live
 *    config) and after save (uses the saved-quote endpoint).
 */

import { useState, useRef, useEffect } from 'react'
import DoorPreview from './DoorPreview'
import { exportAsSVG, exportAsPNG, exportAsPDF, printDrawing, exportDrawingPackage, getSvgFromRef } from '../utils/drawingExport'
import { doorConfigApi } from '../api/client'
import { savedQuotesApi, customerDoorConfigApi } from '../api/customerClient'
import { extrasFromConfig, extrasFromLineItems } from '../utils/doorExtras'

const TABS = [
  { id: 'preview', label: 'Door Preview', icon: '\u{1F6AA}' },
  { id: 'shop_drawing', label: 'Shop Drawing', icon: '\u{1F4D0}' },
]

function DoorDrawings({
  doorConfig = {},
  showExport = true,
  defaultTab = 'preview',
  lineItems = null,
  extras: extrasProp = null,
  savedQuoteId = null,    // when set, "Produce Drawing" uses the saved-quote endpoint
  customerName = null,    // populates the title block in the preview-endpoint flow
  jobNumber = null,
  // Caller side: customer portal sends customer auth, admin tool sends admin
  // auth. Pass "admin" to use the admin axios client; default is customer.
  apiContext = 'customer',
}) {
  // Resolve the optional-extras list for the framing drawing:
  //   1. explicit `extras` prop wins
  //   2. else derive from BC line items if provided
  //   3. else derive from the live doorConfig selections
  const resolvedExtras = Array.isArray(extrasProp)
    ? extrasProp
    : (Array.isArray(lineItems) && lineItems.length > 0
      ? extrasFromLineItems(lineItems)
      : extrasFromConfig(doorConfig))
  const [activeTab, setActiveTab] = useState(defaultTab)
  const [exportFormat, setExportFormat] = useState('pdf')

  // Backend shop drawing PDF state
  const [shopPdfUrl, setShopPdfUrl] = useState(null)
  const [shopPdfLoading, setShopPdfLoading] = useState(false)
  const [shopPdfError, setShopPdfError] = useState(null)

  // Ref for the in-browser door visualization (still SVG)
  const previewRef = useRef(null)

  // Extract door configuration with defaults
  const {
    doorWidth = 96,
    doorHeight = 84,
    panelColor = 'WHITE',
    panelDesign = 'SHXL',
    windowInsert = null,
    windowPositions = [],
    windowSize = 'long',
    windowSection = 1,
    windowQty = 0,
    windowPanels = null,
    windowFrameColor = 'MATCH',
    hasInserts = false,
    glassColor = 'CLEAR',
    doorType = 'residential',
    doorSeries = 'KANATA',
    trackRadius = '15',
    trackThickness = '2',
    liftType: configLiftType = null,
    highLiftInches = null,
    trackMount = 'bracket',
    springCount = null,
    glassPocketsPerSection = null,
  } = doorConfig

  // Convert string values
  const widthInches = parseInt(doorWidth) || 96
  const heightInches = parseInt(doorHeight) || 84
  const radius = parseInt(trackRadius) || 15
  const trackSize = parseInt(trackThickness) || 2

  // Use config-provided lift type, or derive from track settings as fallback
  const liftType = configLiftType || (radius === 12 ? 'low_headroom' : 'standard')

  // Derive frame type from door type
  const frameType = doorType === 'residential' ? 'wood' : 'steel'

  // Invalidate cached preview when the underlying config changes — the user
  // can re-click "Produce Drawing" to regenerate.
  useEffect(() => {
    if (shopPdfUrl) {
      URL.revokeObjectURL(shopPdfUrl)
      setShopPdfUrl(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedQuoteId, widthInches, heightInches, panelDesign, panelColor, doorSeries, liftType, highLiftInches, trackRadius, glassPocketsPerSection])

  // Cleanup blob URL on unmount
  useEffect(() => () => {
    if (shopPdfUrl) URL.revokeObjectURL(shopPdfUrl)
  }, [shopPdfUrl])

  // Pull a single door config out of doorConfig for the preview endpoint.
  // The drawing service expects { doors: [{ ... }] }.
  const buildPreviewConfigData = () => ({
    doors: [{
      doorSeries,
      doorType,
      doorWidth: widthInches,
      doorHeight: heightInches,
      doorCount: doorConfig.doorCount || 1,
      panelDesign,
      panelColor,
      windowInsert: windowInsert || null,
      windowPositions: windowPositions || [],
      windowSize: windowSize || 'long',
      windowSection: windowSection || 1,
      windowQty: windowQty || 0,
      windowPanels: windowPanels || null,
      windowFrameColor: windowFrameColor || 'MATCH',
      glassColor: glassColor || 'CLEAR',
      glassPocketsPerSection: glassPocketsPerSection || null,
      liftType,
      highLiftInches: highLiftInches || null,
      trackRadius: radius,
      trackThickness: trackSize,
      trackMount: trackMount || 'bracket',
    }],
  })

  // Returns a Blob/Response for the requested fmt. Picks the saved-quote
  // endpoint when a savedQuoteId is set, else the preview endpoint.
  const fetchShopDrawing = async (fmt) => {
    if (savedQuoteId) {
      return savedQuotesApi.framingDrawing(savedQuoteId, { fmt })
    }
    const previewApi = apiContext === 'admin'
      ? doorConfigApi.previewFramingDrawing
      : customerDoorConfigApi.previewFramingDrawing
    return previewApi({
      configData: buildPreviewConfigData(),
      customerName,
      jobNumber,
      doorIndex: 0,
      fmt,
    })
  }

  const produceShopDrawing = async () => {
    if (shopPdfLoading) return
    setShopPdfLoading(true)
    setShopPdfError(null)
    try {
      const resp = await fetchShopDrawing('pdf')
      const url = URL.createObjectURL(new Blob([resp.data], { type: 'application/pdf' }))
      // Replace any existing preview URL
      if (shopPdfUrl) URL.revokeObjectURL(shopPdfUrl)
      setShopPdfUrl(url)
    } catch (err) {
      setShopPdfError(err?.response?.data?.detail || err.message || 'Failed to produce drawing')
    } finally {
      setShopPdfLoading(false)
    }
  }

  const downloadShopDrawing = async (fmt) => {
    try {
      const resp = await fetchShopDrawing(fmt)
      const blob = new Blob([resp.data], {
        type: fmt === 'dxf' ? 'application/dxf' : 'application/pdf',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `framing-drawing-${doorSeries}-${widthInches}x${heightInches}.${fmt}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      alert(err?.response?.data?.detail || err.message || 'Failed to download')
    }
  }

  // Handle export of the Door Preview SVG. Shop drawing exports go through
  // the dedicated Download PDF / Download DXF buttons in that tab.
  const handleExport = () => {
    if (activeTab !== 'preview') return
    const filename = `door-preview-${widthInches}x${heightInches}`
    const svg = getSvgFromRef(previewRef)
    if (!svg) {
      alert('Drawing not available for export')
      return
    }
    switch (exportFormat) {
      case 'svg':
        exportAsSVG(svg, `${filename}.svg`)
        break
      case 'png':
        exportAsPNG(svg, `${filename}.png`, 2)
        break
      case 'pdf':
        exportAsPDF(svg, `${filename}.pdf`, `${doorSeries} ${Math.floor(widthInches / 12)}' x ${Math.floor(heightInches / 12)}'`)
        break
      case 'print':
        printDrawing(svg, `Door Drawing - ${doorSeries}`)
        break
      default:
        break
    }
  }

  // Export-all is no longer meaningful (only Preview SVG remains; shop
  // drawing has its own buttons). Kept as a thin wrapper so the existing
  // "Export All" button still works for the Door Preview.
  const handleExportAll = () => {
    const drawings = [
      { element: getSvgFromRef(previewRef), title: 'Door Preview' },
    ].filter(d => d.element)

    if (drawings.length === 0) {
      alert('No drawings available for export')
      return
    }

    exportDrawingPackage(drawings, {
      series: doorSeries,
      width: Math.floor(widthInches / 12),
      height: Math.floor(heightInches / 12),
      color: panelColor,
    })
  }

  return (
    <div className="door-drawings bg-white rounded-lg shadow-sm border border-gray-200">
      {/* Tab Navigation */}
      <div className="border-b border-gray-200">
        <div className="flex items-center justify-between px-4">
          <nav className="flex space-x-4" aria-label="Tabs">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-3 px-1 border-b-2 font-medium text-sm whitespace-nowrap ${
                  activeTab === tab.id
                    ? 'border-odc-500 text-odc-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                <span className="mr-1">{tab.icon}</span>
                {tab.label}
              </button>
            ))}
          </nav>

          {/* Export Controls */}
          {showExport && (
            <div className="flex items-center space-x-2 py-2">
              <select
                value={exportFormat}
                onChange={(e) => setExportFormat(e.target.value)}
                className="text-sm border border-gray-300 rounded px-2 py-1"
              >
                <option value="pdf">PDF</option>
                <option value="svg">SVG</option>
                <option value="png">PNG</option>
                <option value="print">Print</option>
              </select>
              <button
                onClick={handleExport}
                className="px-3 py-1 text-sm bg-odc-600 text-white rounded hover:bg-odc-700"
              >
                Export
              </button>
              <button
                onClick={handleExportAll}
                className="px-3 py-1 text-sm bg-gray-600 text-white rounded hover:bg-gray-700"
                title="Export all drawings as a package"
              >
                Export All
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Drawing Area */}
      <div className="p-4">
        {/* Door Preview Tab */}
        <div ref={previewRef} className={activeTab === 'preview' ? 'block' : 'hidden'}>
          <div className="flex flex-col md:flex-row items-start gap-6">
            <div className="flex-shrink-0">
              <DoorPreview
                width={widthInches}
                height={heightInches}
                color={panelColor}
                panelDesign={panelDesign}
                windowInsert={windowInsert}
                windowPositions={windowPositions}
                windowSize={windowSize}
                windowSection={windowSection}
                windowQty={windowQty}
                windowPanels={windowPanels}
                windowFrameColor={windowFrameColor}
                hasInserts={hasInserts}
                glassColor={glassColor}
                doorType={doorType}
                doorSeries={doorSeries}
                glassPocketsPerSection={glassPocketsPerSection}
                showDimensions={true}
                scale={1}
              />
            </div>
            <div className="flex-grow">
              <h3 className="text-lg font-medium text-gray-900 mb-3">Door Specifications</h3>
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <dt className="text-gray-500">Series:</dt>
                <dd className="font-medium">{doorSeries}</dd>
                <dt className="text-gray-500">Size:</dt>
                <dd className="font-medium">{Math.floor(widthInches / 12)}' x {Math.floor(heightInches / 12)}'</dd>
                <dt className="text-gray-500">Color:</dt>
                <dd className="font-medium">{panelColor.replace(/_/g, ' ')}</dd>
                <dt className="text-gray-500">Panel Design:</dt>
                <dd className="font-medium">{panelDesign}</dd>
                <dt className="text-gray-500">Windows:</dt>
                <dd className="font-medium">{windowInsert && windowInsert !== 'NONE' ? `Yes (Section ${windowSection})` : 'None'}</dd>
                <dt className="text-gray-500">Track:</dt>
                <dd className="font-medium">{trackSize}" / {radius}" radius</dd>
              </dl>
            </div>
          </div>
        </div>

        {/* Shop Drawing Tab — backend-rendered PDF.
             When savedQuoteId is set: hits the saved-quote endpoint (real
             customer/job# in the title block).
             Otherwise: hits the preview endpoint with the live config so
             the in-house tool / pre-save configurator gets the same drawing. */}
        <div className={activeTab === 'shop_drawing' ? 'block' : 'hidden'}>
          <div className="flex flex-wrap items-center gap-3 mb-3">
            <button
              onClick={produceShopDrawing}
              disabled={shopPdfLoading}
              className="px-4 py-2 text-sm font-medium bg-odc-600 text-white rounded hover:bg-odc-700 disabled:opacity-50"
            >
              {shopPdfLoading
                ? 'Generating…'
                : (shopPdfUrl ? 'Regenerate Drawing' : 'Produce Drawing')}
            </button>
            {shopPdfUrl && !shopPdfLoading && (
              <>
                <button
                  onClick={() => downloadShopDrawing('pdf')}
                  className="px-3 py-2 text-sm font-medium bg-gray-700 text-white rounded hover:bg-gray-800"
                >
                  Download PDF
                </button>
                <button
                  onClick={() => downloadShopDrawing('dxf')}
                  className="px-3 py-2 text-sm font-medium bg-gray-700 text-white rounded hover:bg-gray-800"
                  title="DXF for opening in CAD software"
                >
                  Download DXF
                </button>
              </>
            )}
            <span className="text-xs text-gray-500">
              Includes front + side elevations, plan view, panel profile, optional extras checklist, and title block.
            </span>
          </div>

          {shopPdfError && !shopPdfLoading && (
            <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700 mb-3">
              Could not produce shop drawing: {shopPdfError}
            </div>
          )}

          {shopPdfUrl && !shopPdfLoading && (
            <div className="border border-gray-300 rounded">
              <iframe
                src={shopPdfUrl}
                title="Shop Drawing PDF"
                style={{ width: '100%', height: '70vh', minHeight: 500, border: 0 }}
              />
            </div>
          )}

          {!shopPdfUrl && !shopPdfLoading && !shopPdfError && (
            <div className="text-center py-16 text-gray-500 border border-dashed border-gray-300 rounded">
              Click <strong>Produce Drawing</strong> to generate the shop drawing PDF.
              <br />
              <span className="text-xs">No save required — the drawing is generated from the current configuration.</span>
            </div>
          )}
        </div>
      </div>

      {/* Quick Actions */}
      <div className="border-t border-gray-200 px-4 py-3 bg-gray-50 flex justify-between items-center">
        <div className="text-sm text-gray-500">
          {doorSeries} {Math.floor(widthInches / 12)}' x {Math.floor(heightInches / 12)}' - {panelColor.replace(/_/g, ' ')}
        </div>
        <div className="flex space-x-2">
          <button
            onClick={() => window.print()}
            className="text-sm text-gray-600 hover:text-gray-800"
          >
            Print Current View
          </button>
        </div>
      </div>
    </div>
  )
}

export default DoorDrawings
