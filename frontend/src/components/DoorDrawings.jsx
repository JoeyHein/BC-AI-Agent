/**
 * DoorDrawings Component
 * Combined view for all door drawings with export functionality
 * Includes: Visual Preview, Framing Drawing, Side Elevation
 */

import { useState, useRef } from 'react'
import DoorPreview from './DoorPreview'
import FramingDrawing from './FramingDrawing'
import SideElevationDrawing from './SideElevationDrawing'
import { exportAsSVG, exportAsPNG, printDrawing, exportDrawingPackage, getSvgFromRef } from '../utils/drawingExport'

const TABS = [
  { id: 'preview', label: 'Door Preview', icon: '🚪' },
  { id: 'framing', label: 'Framing Drawing', icon: '📐' },
  { id: 'elevation', label: 'Side Elevation', icon: '📏' },
]

function DoorDrawings({
  doorConfig = {},
  showExport = true,
  defaultTab = 'preview',
}) {
  const [activeTab, setActiveTab] = useState(defaultTab)
  const [exportFormat, setExportFormat] = useState('svg')

  // Refs for each drawing
  const previewRef = useRef(null)
  const framingRef = useRef(null)
  const elevationRef = useRef(null)

  // Extract door configuration with defaults
  const {
    doorWidth = 96,
    doorHeight = 84,
    panelColor = 'WHITE',
    panelDesign = 'SHXL',
    windowInsert = null,
    windowPositions = [],
    windowSection = 1,
    windowQty = 0,
    windowFrameColor = 'MATCH',
    hasInserts = false,
    glassColor = 'CLEAR',
    doorType = 'residential',
    doorSeries = 'KANATA',
    trackRadius = '15',
    trackThickness = '2',
  } = doorConfig

  // Convert string values
  const widthInches = parseInt(doorWidth) || 96
  const heightInches = parseInt(doorHeight) || 84
  const radius = parseInt(trackRadius) || 15
  const trackSize = parseInt(trackThickness) || 2

  // Determine lift type from track settings
  const liftType = radius === 12 ? 'low_headroom' : 'standard'

  // Handle export
  const handleExport = () => {
    let ref, filename
    switch (activeTab) {
      case 'preview':
        ref = previewRef
        filename = `door-preview-${widthInches}x${heightInches}`
        break
      case 'framing':
        ref = framingRef
        filename = `framing-drawing-${widthInches}x${heightInches}`
        break
      case 'elevation':
        ref = elevationRef
        filename = `side-elevation-${widthInches}x${heightInches}`
        break
      default:
        return
    }

    const svg = getSvgFromRef(ref)
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
      case 'print':
        printDrawing(svg, `Door Drawing - ${doorSeries}`)
        break
      default:
        break
    }
  }

  // Handle export all
  const handleExportAll = () => {
    const drawings = [
      { element: getSvgFromRef(previewRef), title: 'Door Preview' },
      { element: getSvgFromRef(framingRef), title: 'Framing Drawing' },
      { element: getSvgFromRef(elevationRef), title: 'Side Elevation' },
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
                    ? 'border-indigo-500 text-indigo-600'
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
                <option value="svg">SVG</option>
                <option value="png">PNG</option>
                <option value="print">Print</option>
              </select>
              <button
                onClick={handleExport}
                className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700"
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
                windowSection={windowSection}
                windowQty={windowQty}
                windowFrameColor={windowFrameColor}
                hasInserts={hasInserts}
                glassColor={glassColor}
                doorType={doorType}
                doorSeries={doorSeries}
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

        {/* Framing Drawing Tab */}
        <div ref={framingRef} className={activeTab === 'framing' ? 'block' : 'hidden'}>
          <div className="overflow-x-auto">
            <FramingDrawing
              width={widthInches}
              height={heightInches}
              trackRadius={radius}
              trackSize={trackSize}
              liftType={liftType}
              showSpringAssembly={true}
              showHardwareLocations={true}
              showDimensions={true}
              scale={0.6}
              title={`FRAMING DRAWING - ${doorSeries}`}
            />
          </div>
          <div className="mt-4 p-3 bg-blue-50 rounded-lg">
            <p className="text-sm text-blue-800">
              <strong>Note:</strong> This drawing shows framing requirements for installation.
              Verify all dimensions on site before proceeding with construction.
            </p>
          </div>
        </div>

        {/* Side Elevation Tab */}
        <div ref={elevationRef} className={activeTab === 'elevation' ? 'block' : 'hidden'}>
          <div className="overflow-x-auto">
            <SideElevationDrawing
              width={widthInches}
              height={heightInches}
              trackRadius={radius}
              trackSize={trackSize}
              liftType={liftType}
              scale={0.6}
              title={`SIDE ELEVATION - ${doorSeries}`}
            />
          </div>
          <div className="mt-4 p-3 bg-yellow-50 rounded-lg">
            <p className="text-sm text-yellow-800">
              <strong>Clearance Requirements:</strong> Ensure adequate head room, back room,
              and side room clearances as shown in the drawing before installation.
            </p>
          </div>
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
