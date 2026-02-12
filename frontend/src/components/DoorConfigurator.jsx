import { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { doorConfigApi } from '../api/client'
import DoorDrawings from './DoorDrawings'
import DoorPreview from './DoorPreview'

const STEPS = [
  { id: 'type', title: 'Door Type', description: 'Select door category' },
  { id: 'series', title: 'Series', description: 'Choose door series' },
  { id: 'dimensions', title: 'Dimensions', description: 'Set size and quantity' },
  { id: 'design', title: 'Design', description: 'Color and panel style' },
  { id: 'windows', title: 'Windows', description: 'Window configuration' },
  { id: 'hardware', title: 'Hardware', description: 'Track and hardware' },
  { id: 'drawings', title: 'Drawings', description: 'View door drawings' },
  { id: 'review', title: 'Review', description: 'Review and submit' },
]

function DoorConfigurator() {
  const [currentStep, setCurrentStep] = useState(0)
  const [doors, setDoors] = useState([createEmptyDoor()])
  const [currentDoorIndex, setCurrentDoorIndex] = useState(0)
  const [quoteResult, setQuoteResult] = useState(null)

  // Fetch full configuration on mount
  const { data: config, isLoading: configLoading } = useQuery({
    queryKey: ['doorConfig'],
    queryFn: async () => {
      const response = await doorConfigApi.getFullConfig()
      return response.data.data
    },
  })

  const generateQuoteMutation = useMutation({
    mutationFn: (request) => doorConfigApi.generateQuote(request),
    onSuccess: (response) => {
      setQuoteResult(response.data)
      alert('Quote generated successfully!')
    },
    onError: (error) => {
      alert(`Error generating quote: ${error.response?.data?.detail || error.message}`)
    }
  })

  const validateMutation = useMutation({
    mutationFn: (doorConfig) => doorConfigApi.validateConfig(doorConfig),
  })

  function createEmptyDoor() {
    return {
      doorType: '',
      doorSeries: '',
      doorWidth: 96,
      doorHeight: 84,
      doorCount: 1,
      panelColor: '',
      panelDesign: '',
      // Window configuration
      hasWindows: false,
      windowPositions: [],  // Array of {section, col} for multi-stamp windows
      glassPaneType: null,  // 'INSULATED' or 'SINGLE'
      glassColor: null,  // 'CLEAR', 'ETCHED', 'SUPER_GREY'
      hasInserts: false,  // Whether decorative inserts are added
      windowInsert: 'NONE',  // Insert style if hasInserts is true
      windowSection: 1,  // Legacy fallback
      glazingType: 'NONE',  // Legacy
      // Hardware
      trackRadius: '15',
      trackThickness: '2',
      liftType: 'standard',
      hardware: {
        tracks: true,
        springs: true,
        struts: true,
        hardwareKits: true,
        weatherStripping: true,
        bottomRetainer: true,
        shafts: true,
      },
      operator: 'NONE',
      // Spring and shaft options
      targetCycles: 10000,
      shaftType: 'auto', // 'auto', 'single', 'split'
    }
  }

  const currentDoor = doors[currentDoorIndex]

  function updateCurrentDoor(updates) {
    setDoors(prev => {
      const newDoors = [...prev]
      newDoors[currentDoorIndex] = { ...newDoors[currentDoorIndex], ...updates }
      return newDoors
    })
  }

  function addDoor() {
    setDoors(prev => [...prev, createEmptyDoor()])
    setCurrentDoorIndex(doors.length)
    setCurrentStep(0)
  }

  function removeDoor(index) {
    if (doors.length === 1) return
    setDoors(prev => prev.filter((_, i) => i !== index))
    if (currentDoorIndex >= doors.length - 1) {
      setCurrentDoorIndex(Math.max(0, doors.length - 2))
    }
  }

  function nextStep() {
    if (currentStep < STEPS.length - 1) {
      setCurrentStep(currentStep + 1)
    }
  }

  function prevStep() {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1)
    }
  }

  function canProceed() {
    const door = currentDoor
    switch (STEPS[currentStep].id) {
      case 'type':
        return !!door.doorType
      case 'series':
        return !!door.doorSeries
      case 'dimensions':
        return door.doorWidth > 0 && door.doorHeight > 0 && door.doorCount > 0
      case 'design':
        return !!door.panelColor && !!door.panelDesign
      case 'windows':
        return true // Windows are optional
      case 'hardware':
        return true // Hardware has defaults
      case 'review':
        return true
      default:
        return true
    }
  }

  async function handleGenerateQuote() {
    const request = {
      doors: doors.map(door => ({
        doorType: door.doorType,
        doorSeries: door.doorSeries,
        doorWidth: door.doorWidth,
        doorHeight: door.doorHeight,
        doorCount: door.doorCount,
        panelColor: door.panelColor,
        panelDesign: door.panelDesign,
        // Window configuration
        hasWindows: door.hasWindows || false,
        windowPositions: door.windowPositions || [],
        glassPaneType: door.glassPaneType,
        glassColor: door.glassColor,
        hasInserts: door.hasInserts || false,
        windowInsert: door.hasInserts && door.windowInsert !== 'NONE' ? door.windowInsert : null,
        windowSection: door.windowSection,  // Legacy fallback
        glazingType: door.glazingType !== 'NONE' ? door.glazingType : null,  // Legacy
        // Hardware
        trackRadius: door.trackRadius,
        trackThickness: door.trackThickness,
        hardware: door.hardware,
        operator: door.operator !== 'NONE' ? door.operator : null,
        // Spring and shaft options
        targetCycles: door.targetCycles || 10000,
        shaftType: door.shaftType || 'auto',
      })),
      tagName: `Configurator Quote - ${doors.length} door(s)`,
    }
    generateQuoteMutation.mutate(request)
  }

  if (configLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-gray-500">Loading configuration...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white shadow rounded-lg p-6">
        <h1 className="text-2xl font-bold text-gray-900">Door Configurator</h1>
        <p className="mt-1 text-sm text-gray-500">
          Build your custom door configuration step by step
        </p>
      </div>

      {/* Door Tabs */}
      {doors.length > 1 && (
        <div className="bg-white shadow rounded-lg p-4">
          <div className="flex items-center space-x-2 overflow-x-auto">
            {doors.map((door, index) => (
              <button
                key={index}
                onClick={() => {
                  setCurrentDoorIndex(index)
                  setCurrentStep(0)
                }}
                className={`flex items-center px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap ${
                  currentDoorIndex === index
                    ? 'bg-indigo-100 text-indigo-700'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                Door {index + 1}
                {door.doorSeries && ` - ${door.doorSeries}`}
                {doors.length > 1 && (
                  <span
                    onClick={(e) => {
                      e.stopPropagation()
                      removeDoor(index)
                    }}
                    className="ml-2 text-gray-400 hover:text-red-500 cursor-pointer"
                  >
                    ×
                  </span>
                )}
              </button>
            ))}
            <button
              onClick={addDoor}
              className="flex items-center px-4 py-2 rounded-lg text-sm font-medium bg-green-100 text-green-700 hover:bg-green-200"
            >
              + Add Door
            </button>
          </div>
        </div>
      )}

      {/* Progress Steps */}
      <div className="bg-white shadow rounded-lg p-4">
        <nav aria-label="Progress">
          <ol className="flex items-center">
            {STEPS.map((step, index) => (
              <li key={step.id} className={`relative ${index !== STEPS.length - 1 ? 'pr-8 sm:pr-20 flex-1' : ''}`}>
                <div className="flex items-center">
                  <button
                    onClick={() => setCurrentStep(index)}
                    className={`relative flex h-8 w-8 items-center justify-center rounded-full ${
                      index < currentStep
                        ? 'bg-indigo-600 hover:bg-indigo-800'
                        : index === currentStep
                        ? 'border-2 border-indigo-600 bg-white'
                        : 'border-2 border-gray-300 bg-white'
                    }`}
                  >
                    {index < currentStep ? (
                      <svg className="h-5 w-5 text-white" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    ) : (
                      <span className={index === currentStep ? 'text-indigo-600' : 'text-gray-500'}>
                        {index + 1}
                      </span>
                    )}
                  </button>
                  {index !== STEPS.length - 1 && (
                    <div className={`absolute top-4 w-full h-0.5 ${index < currentStep ? 'bg-indigo-600' : 'bg-gray-300'}`} style={{ left: '2rem' }} />
                  )}
                </div>
                <div className="mt-2 hidden sm:block">
                  <span className={`text-xs font-medium ${index <= currentStep ? 'text-indigo-600' : 'text-gray-500'}`}>
                    {step.title}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        </nav>
      </div>

      {/* Step Content */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">
          {STEPS[currentStep].title}
        </h2>

        {/* Step 1: Door Type */}
        {STEPS[currentStep].id === 'type' && config && (
          <DoorTypeStep
            doorTypes={config.doorTypes}
            selected={currentDoor.doorType}
            onSelect={(type) => updateCurrentDoor({ doorType: type, doorSeries: '', panelColor: '', panelDesign: '' })}
          />
        )}

        {/* Step 2: Door Series */}
        {STEPS[currentStep].id === 'series' && config && (
          <DoorSeriesStep
            series={config.doorSeries[currentDoor.doorType] || []}
            selected={currentDoor.doorSeries}
            onSelect={(series) => updateCurrentDoor({ doorSeries: series, panelColor: '', panelDesign: '' })}
          />
        )}

        {/* Step 3: Dimensions */}
        {STEPS[currentStep].id === 'dimensions' && (
          <DimensionsStep
            door={currentDoor}
            onChange={updateCurrentDoor}
            series={config?.doorSeries[currentDoor.doorType]?.find(s => s.id === currentDoor.doorSeries)}
          />
        )}

        {/* Step 4: Design */}
        {STEPS[currentStep].id === 'design' && config && (
          <DesignStep
            door={currentDoor}
            colors={config.colors}
            panelDesigns={config.panelDesigns}
            onChange={updateCurrentDoor}
          />
        )}

        {/* Step 5: Windows */}
        {STEPS[currentStep].id === 'windows' && config && (
          <WindowsStep
            door={currentDoor}
            windowInserts={config.windowInserts}
            glazingOptions={config.glazingOptions}
            onChange={updateCurrentDoor}
          />
        )}

        {/* Step 6: Hardware */}
        {STEPS[currentStep].id === 'hardware' && config && (
          <HardwareStep
            door={currentDoor}
            trackOptions={config.trackOptions}
            hardwareOptions={config.hardwareOptions}
            operatorOptions={config.operatorOptions}
            onChange={updateCurrentDoor}
          />
        )}

        {/* Step 7: Drawings */}
        {STEPS[currentStep].id === 'drawings' && (
          <div className="space-y-4">
            <div className="text-sm text-gray-600 mb-4">
              View and export door drawings including visual preview, framing diagram, and side elevation.
              Use these drawings for installation planning and architectural documentation.
            </div>
            <DoorDrawings
              doorConfig={currentDoor}
              showExport={true}
              defaultTab="preview"
            />
          </div>
        )}

        {/* Step 8: Review */}
        {STEPS[currentStep].id === 'review' && (
          <ReviewStep
            doors={doors}
            config={config}
            onGenerateQuote={handleGenerateQuote}
            isGenerating={generateQuoteMutation.isPending}
            quoteResult={quoteResult}
          />
        )}
      </div>

      {/* Navigation */}
      <div className="flex justify-between">
        <button
          onClick={prevStep}
          disabled={currentStep === 0}
          className="inline-flex items-center px-4 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          ← Previous
        </button>
        <div className="flex space-x-3">
          {doors.length === 1 && currentStep === STEPS.length - 1 && (
            <button
              onClick={addDoor}
              className="inline-flex items-center px-4 py-2 border border-green-300 shadow-sm text-sm font-medium rounded-md text-green-700 bg-white hover:bg-green-50"
            >
              + Add Another Door
            </button>
          )}
          {currentStep < STEPS.length - 1 ? (
            <button
              onClick={nextStep}
              disabled={!canProceed()}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Next →
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

// Step Components

function DoorTypeStep({ doorTypes, selected, onSelect }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {doorTypes.map((type) => (
        <button
          key={type.id}
          onClick={() => onSelect(type.id)}
          className={`p-4 rounded-lg border-2 text-left transition-all ${
            selected === type.id
              ? 'border-indigo-500 bg-indigo-50'
              : 'border-gray-200 hover:border-gray-300'
          }`}
        >
          <h3 className="font-medium text-gray-900">{type.name}</h3>
          <p className="mt-1 text-sm text-gray-500">{type.description}</p>
        </button>
      ))}
    </div>
  )
}

function DoorSeriesStep({ series, selected, onSelect }) {
  if (!series.length) {
    return <p className="text-gray-500">Please select a door type first.</p>
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {series.map((s) => (
        <button
          key={s.id}
          onClick={() => onSelect(s.id)}
          className={`p-4 rounded-lg border-2 text-left transition-all ${
            selected === s.id
              ? 'border-indigo-500 bg-indigo-50'
              : 'border-gray-200 hover:border-gray-300'
          }`}
        >
          <h3 className="font-medium text-gray-900">{s.name}</h3>
          <p className="mt-1 text-sm text-gray-500">{s.description}</p>
          {s.specs && (
            <div className="mt-2 text-xs text-gray-400">
              {s.specs.rValue && <span className="mr-3">R-{s.specs.rValue}</span>}
              {s.specs.thickness && <span>{s.specs.thickness}</span>}
            </div>
          )}
        </button>
      ))}
    </div>
  )
}

function DimensionsStep({ door, onChange, series }) {
  const specs = series?.specs || {}

  // Common door sizes
  const commonSizes = [
    { width: 96, height: 84, label: "8' x 7'" },
    { width: 108, height: 84, label: "9' x 7'" },
    { width: 144, height: 84, label: "12' x 7'" },
    { width: 192, height: 84, label: "16' x 7'" },
    { width: 96, height: 96, label: "8' x 8'" },
    { width: 108, height: 96, label: "9' x 8'" },
    { width: 144, height: 96, label: "12' x 8'" },
    { width: 192, height: 96, label: "16' x 8'" },
  ]

  return (
    <div className="space-y-6">
      {/* Quick Select */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Common Sizes
        </label>
        <div className="grid grid-cols-4 gap-2">
          {commonSizes.map((size) => (
            <button
              key={`${size.width}x${size.height}`}
              onClick={() => onChange({ doorWidth: size.width, doorHeight: size.height })}
              className={`px-3 py-2 text-sm rounded-md border ${
                door.doorWidth === size.width && door.doorHeight === size.height
                  ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                  : 'border-gray-300 hover:border-gray-400'
              }`}
            >
              {size.label}
            </button>
          ))}
        </div>
      </div>

      {/* Custom Dimensions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Width (inches)
          </label>
          <input
            type="number"
            value={door.doorWidth}
            onChange={(e) => onChange({ doorWidth: parseInt(e.target.value) || 0 })}
            min={specs.minWidth || 60}
            max={specs.maxWidth || 288}
            className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-indigo-500 focus:border-indigo-500"
          />
          <p className="mt-1 text-xs text-gray-500">
            {Math.floor(door.doorWidth / 12)}' {door.doorWidth % 12}"
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Height (inches)
          </label>
          <input
            type="number"
            value={door.doorHeight}
            onChange={(e) => onChange({ doorHeight: parseInt(e.target.value) || 0 })}
            min={specs.minHeight || 72}
            max={specs.maxHeight || 192}
            className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-indigo-500 focus:border-indigo-500"
          />
          <p className="mt-1 text-xs text-gray-500">
            {Math.floor(door.doorHeight / 12)}' {door.doorHeight % 12}"
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Quantity
          </label>
          <input
            type="number"
            value={door.doorCount}
            onChange={(e) => onChange({ doorCount: parseInt(e.target.value) || 1 })}
            min={1}
            max={100}
            className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>
      </div>

      {/* Constraints Info */}
      {specs.maxWidth && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
          <p className="text-sm text-blue-700">
            <strong>{series?.name}:</strong> Max width {specs.maxWidth}" ({Math.floor(specs.maxWidth / 12)}')
            {specs.sectionHeights && `, Section heights: ${specs.sectionHeights.join('", ')}`}
          </p>
        </div>
      )}
    </div>
  )
}

function DesignStep({ door, colors, panelDesigns, onChange }) {
  // Get colors for current series
  const colorMap = {
    'KANATA': 'KANATA',
    'CRAFT': 'CRAFT',
    'TX450': 'COMMERCIAL',
    'TX500': 'COMMERCIAL',
    'TX450-20': 'COMMERCIAL',
    'TX500-20': 'COMMERCIAL',
    'AL976': 'AL976',
    'KANATA_EXECUTIVE': 'EXECUTIVE_STAINS',
  }
  const colorKey = colorMap[door.doorSeries] || 'KANATA'
  const availableColors = colors[colorKey] || colors['KANATA'] || []

  // Get panel designs for current series
  // Commercial doors: TX450/TX500 = UDC only, TX450-20/TX500-20 = Flush + UDC
  const designMap = {
    'KANATA': 'KANATA',
    'CRAFT': 'CRAFT',
    'KANATA_EXECUTIVE': 'EXECUTIVE',
    'TX450': 'COMMERCIAL',
    'TX500': 'COMMERCIAL',
    'TX450-20': 'COMMERCIAL_20',
    'TX500-20': 'COMMERCIAL_20',
  }
  const designKey = designMap[door.doorSeries] || 'KANATA'
  const availableDesigns = panelDesigns[designKey] || []

  return (
    <div className="space-y-6">
      {/* Colors */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Panel Color
        </label>
        <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
          {availableColors.map((color) => (
            <button
              key={color.id}
              onClick={() => onChange({ panelColor: color.id })}
              className={`p-3 rounded-lg border-2 text-center transition-all ${
                door.panelColor === color.id
                  ? 'border-indigo-500 ring-2 ring-indigo-200'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              {/* Color swatch - with woodgrain pattern for wood finishes */}
              {color.type === 'woodgrain' && color.grain ? (
                <svg className="w-10 h-10 rounded-full mx-auto border border-gray-300 overflow-hidden" viewBox="0 0 40 40">
                  <rect width="40" height="40" fill={color.grain[0]} />
                  <path d="M0,8 Q10,6 20,8 T40,8" stroke={color.grain[2]} strokeWidth="1" fill="none" opacity="0.7" />
                  <path d="M0,16 Q15,14 30,16 T40,16" stroke={color.grain[1]} strokeWidth="0.8" fill="none" opacity="0.5" />
                  <path d="M0,24 Q12,22 24,24 T40,24" stroke={color.grain[2]} strokeWidth="1" fill="none" opacity="0.6" />
                  <path d="M0,32 Q8,30 16,32 T40,32" stroke={color.grain[1]} strokeWidth="0.8" fill="none" opacity="0.5" />
                </svg>
              ) : (
                <div
                  className="w-10 h-10 rounded-full mx-auto border border-gray-300"
                  style={{ backgroundColor: color.hex || '#ccc' }}
                />
              )}
              <span className="mt-1 block text-xs text-gray-700">{color.name}</span>
              {color.ral && <span className="block text-xs text-gray-400">{color.ral}</span>}
              {color.note && <span className="block text-xs text-orange-500">{color.note}</span>}
            </button>
          ))}
        </div>
      </div>

      {/* Panel Designs */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Panel Design
        </label>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {availableDesigns.map((design) => (
            <button
              key={design.id}
              onClick={() => onChange({ panelDesign: design.code || design.id })}
              className={`p-4 rounded-lg border-2 text-left transition-all ${
                door.panelDesign === (design.code || design.id)
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <h4 className="font-medium text-gray-900">{design.name}</h4>
              <p className="mt-1 text-xs text-gray-500">{design.type}</p>
              {design.code && <p className="mt-1 text-xs text-gray-400">Code: {design.code}</p>}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// Window Insert Preview Component - renders SVG representations
function WindowInsertPreview({ insertId, size = 60 }) {
  const width = size
  const height = size * 0.6  // Window aspect ratio

  // Define grid patterns for different insert types
  const getGridPattern = () => {
    switch (insertId) {
      case 'STOCKTON_STANDARD':
        return { rows: 2, cols: 4, arched: false }
      case 'STOCKTON_TEN_SQUARE_XL':
        return { rows: 2, cols: 5, arched: false }
      case 'STOCKTON_ARCHED_XL':
        return { rows: 2, cols: 5, arched: true }
      case 'STOCKTON_EIGHT_SQUARE':
        return { rows: 2, cols: 4, arched: false }
      case 'STOCKTON_ARCHED':
        return { rows: 2, cols: 4, arched: true }
      case 'STOCKBRIDGE_STRAIGHT':
        return { type: 'prairie', arched: false }
      case 'STOCKBRIDGE_STRAIGHT_XL':
        return { type: 'prairie', arched: false, xl: true }
      case 'STOCKBRIDGE_ARCHED_XL':
        return { type: 'prairie', arched: true, xl: true }
      case 'STOCKBRIDGE_ARCHED':
        return { type: 'prairie', arched: true }
      default:
        return { rows: 2, cols: 4, arched: false }
    }
  }

  const pattern = getGridPattern()
  const frameColor = '#444'
  const glassColor = '#87CEEB'

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {/* Glass background */}
      <rect x={2} y={2} width={width - 4} height={height - 4} fill={glassColor} rx={2} />

      {/* Frame */}
      <rect x={2} y={2} width={width - 4} height={height - 4} fill="none" stroke={frameColor} strokeWidth={2} rx={2} />

      {pattern.type === 'prairie' ? (
        // Prairie style - border pattern with center clear
        <>
          <rect
            x={width * 0.15}
            y={height * 0.2}
            width={width * 0.7}
            height={height * 0.6}
            fill="none"
            stroke={frameColor}
            strokeWidth={1.5}
          />
          {/* Corner squares */}
          {[[2, 2], [width - width * 0.15, 2], [2, height - height * 0.2], [width - width * 0.15, height - height * 0.2]].map(([cx, cy], i) => (
            <rect key={i} x={cx} y={cy} width={width * 0.12} height={height * 0.18} fill="none" stroke={frameColor} strokeWidth={1} />
          ))}
          {pattern.arched && (
            <path
              d={`M 4 ${height * 0.25} Q ${width / 2} ${-height * 0.1} ${width - 4} ${height * 0.25}`}
              fill="none"
              stroke={frameColor}
              strokeWidth={1.5}
            />
          )}
        </>
      ) : (
        // Grid pattern
        <>
          {/* Vertical grid lines */}
          {[...Array(pattern.cols - 1)].map((_, i) => {
            const x = 2 + ((width - 4) / pattern.cols) * (i + 1)
            return <line key={`v${i}`} x1={x} y1={2} x2={x} y2={height - 2} stroke={frameColor} strokeWidth={1.5} />
          })}
          {/* Horizontal grid lines */}
          {[...Array(pattern.rows - 1)].map((_, i) => {
            const y = 2 + ((height - 4) / pattern.rows) * (i + 1)
            return <line key={`h${i}`} x1={2} y1={y} x2={width - 2} y2={y} stroke={frameColor} strokeWidth={1.5} />
          })}
          {/* Arched top */}
          {pattern.arched && (
            <path
              d={`M 4 ${height * 0.3} Q ${width / 2} ${-height * 0.15} ${width - 4} ${height * 0.3}`}
              fill="none"
              stroke={frameColor}
              strokeWidth={2}
            />
          )}
        </>
      )}

      {/* Reflection */}
      <rect x={4} y={4} width={width * 0.2} height={height * 0.3} fill="white" opacity={0.3} rx={1} />
    </svg>
  )
}

function WindowsStep({ door, windowInserts, glazingOptions, onChange }) {
  const [hoveredStamp, setHoveredStamp] = useState(null)
  const hasWindows = door.hasWindows || false

  // Calculate panel count based on height (matching DoorPreview.jsx sectionConfig)
  const getPanelCount = (heightInches) => {
    if (heightInches <= 96) return 4   // 7' and 8' doors = 4 panels
    if (heightInches <= 120) return 5  // 9' and 10' doors = 5 panels
    if (heightInches <= 144) return 6  // 11' and 12' doors = 6 panels
    if (heightInches <= 168) return 7  // 13' and 14' doors = 7 panels
    return 8
  }
  const panelCount = getPanelCount(door.doorHeight)

  // Calculate stamp columns based on door width (same logic as DoorPreview)
  const getStampColumns = (widthInches) => {
    const widthFeet = widthInches / 12
    if (widthFeet <= 12) return 3
    if (widthFeet <= 16) return 4
    if (widthFeet <= 19) return 5
    return 6
  }
  const stampColumns = getStampColumns(door.doorWidth)

  // Get window positions, defaulting to empty array
  const windowPositions = door.windowPositions || []

  // Check if a position has a window
  const hasWindowAt = (section, col) => {
    return windowPositions.some(pos => pos.section === section && pos.col === col)
  }

  // Toggle window at a stamp position
  const toggleWindow = (section, col) => {
    const existing = windowPositions.find(pos => pos.section === section && pos.col === col)
    let newPositions
    if (existing) {
      newPositions = windowPositions.filter(pos => !(pos.section === section && pos.col === col))
    } else {
      newPositions = [...windowPositions, { section, col }]
    }
    onChange({ windowPositions: newPositions })
  }

  // Quick actions for common patterns
  const setTopRowWindows = () => {
    const positions = []
    for (let col = 0; col < stampColumns; col++) {
      positions.push({ section: 1, col })
    }
    onChange({ windowPositions: positions })
  }

  const setLeftColumnWindows = () => {
    const positions = []
    for (let section = 1; section <= panelCount; section++) {
      positions.push({ section, col: 0 })
    }
    onChange({ windowPositions: positions })
  }

  const setRightColumnWindows = () => {
    const positions = []
    for (let section = 1; section <= panelCount; section++) {
      positions.push({ section, col: stampColumns - 1 })
    }
    onChange({ windowPositions: positions })
  }

  const clearAllWindows = () => {
    onChange({ windowPositions: [] })
  }

  // Glass color options with visual representation
  const glassColorOptions = [
    { id: 'CLEAR', name: 'Clear', color: '#87CEEB', description: 'Standard clear glass' },
    { id: 'ETCHED', name: 'Etched', color: '#D3D3D3', description: 'Frosted privacy glass' },
    { id: 'SUPER_GREY', name: 'Super Grey', color: '#2D2D2D', description: 'Dark tinted glass' },
  ]

  // Glass pane type options
  const glassPaneOptions = [
    { id: 'INSULATED', name: 'Insulated', description: 'Double-pane for energy efficiency' },
    { id: 'SINGLE', name: 'Single Pane', description: 'Standard single glass' },
  ]

  return (
    <div className="space-y-6">
      {/* Window Toggle */}
      <div className="flex items-center space-x-3">
        <input
          type="checkbox"
          id="hasWindows"
          checked={hasWindows}
          onChange={(e) => onChange({
            hasWindows: e.target.checked,
            windowPositions: e.target.checked ? [] : [],
            glassPaneType: e.target.checked ? 'INSULATED' : null,
            glassColor: e.target.checked ? 'CLEAR' : null,
            windowInsert: 'NONE',
            hasInserts: false,
          })}
          className="h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded"
        />
        <label htmlFor="hasWindows" className="text-sm font-medium text-gray-700">
          Include windows in this door
        </label>
      </div>

      {hasWindows && (
        <>
          {/* Step 1: Window Placement - Interactive Door Preview */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              1. Select Window Positions
            </label>
            <p className="text-xs text-gray-500 mb-3">Click stamps to add/remove windows</p>
            <div className="flex flex-col lg:flex-row gap-6">
              {/* Interactive Door Preview */}
              <div className="flex-shrink-0">
                <DoorPreview
                  width={door.doorWidth}
                  height={door.doorHeight}
                  color={door.panelColor || 'WHITE'}
                  panelDesign={door.panelDesign || 'SHXL'}
                  windowInsert={door.windowInsert}
                  windowPositions={windowPositions}
                  hasInserts={door.hasInserts || false}
                  glassColor={door.glassColor || 'CLEAR'}
                  showDimensions={false}
                  scale={0.7}
                  interactive={true}
                  onStampClick={toggleWindow}
                  highlightStamp={hoveredStamp}
                  onStampHover={(section, col) => setHoveredStamp(section !== null ? { section, col } : null)}
                />
                <p className="mt-2 text-xs text-center text-gray-500">
                  Click any stamp to toggle window
                </p>
              </div>

              {/* Quick Actions & Info */}
              <div className="flex-1 space-y-4">
                {/* Quick Actions */}
                <div>
                  <p className="text-sm font-medium text-gray-700 mb-2">Quick Patterns:</p>
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={setTopRowWindows}
                      className="px-3 py-2 text-xs rounded-md border border-gray-300 hover:border-indigo-400 hover:bg-indigo-50"
                    >
                      Top Row
                    </button>
                    <button
                      onClick={setLeftColumnWindows}
                      className="px-3 py-2 text-xs rounded-md border border-gray-300 hover:border-indigo-400 hover:bg-indigo-50"
                    >
                      Left Column
                    </button>
                    <button
                      onClick={setRightColumnWindows}
                      className="px-3 py-2 text-xs rounded-md border border-gray-300 hover:border-indigo-400 hover:bg-indigo-50"
                    >
                      Right Column
                    </button>
                    <button
                      onClick={clearAllWindows}
                      className="px-3 py-2 text-xs rounded-md border border-red-200 text-red-600 hover:border-red-400 hover:bg-red-50"
                    >
                      Clear All
                    </button>
                  </div>
                </div>

                {/* Grid Info */}
                <div className="p-3 bg-gray-50 rounded-md">
                  <p className="text-sm text-gray-600">
                    <strong>Door Grid:</strong> {panelCount} sections × {stampColumns} stamps
                  </p>
                  <p className="text-sm text-gray-600 mt-1">
                    <strong>Windows Selected:</strong> {windowPositions.length}
                  </p>
                </div>

                {/* Selected Windows List */}
                {windowPositions.length > 0 && (
                  <div className="p-3 bg-indigo-50 rounded-md">
                    <p className="text-sm font-medium text-indigo-700 mb-2">Window Positions:</p>
                    <div className="flex flex-wrap gap-1">
                      {windowPositions.map((pos, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center px-2 py-1 text-xs rounded bg-white border border-indigo-200 text-indigo-700"
                        >
                          S{pos.section}-C{pos.col + 1}
                          <button
                            onClick={() => toggleWindow(pos.section, pos.col)}
                            className="ml-1 text-indigo-400 hover:text-red-500"
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Stamp Grid Selector (alternative to clicking preview) */}
                <div>
                  <p className="text-sm font-medium text-gray-700 mb-2">Or click grid cells:</p>
                  <div className="inline-block border border-gray-300 rounded-lg p-2 bg-white">
                    {[...Array(panelCount)].map((_, section) => (
                      <div key={section} className="flex gap-1 mb-1 last:mb-0">
                        {[...Array(stampColumns)].map((_, col) => (
                          <button
                            key={col}
                            onClick={() => toggleWindow(section + 1, col)}
                            onMouseEnter={() => setHoveredStamp({ section: section + 1, col })}
                            onMouseLeave={() => setHoveredStamp(null)}
                            className={`w-8 h-8 rounded text-xs font-medium transition-all ${
                              hasWindowAt(section + 1, col)
                                ? 'bg-sky-400 text-white border-2 border-sky-500'
                                : hoveredStamp?.section === section + 1 && hoveredStamp?.col === col
                                  ? 'bg-blue-100 border-2 border-blue-300'
                                  : 'bg-gray-100 border border-gray-300 hover:bg-gray-200'
                            }`}
                            title={`Section ${section + 1}, Column ${col + 1}`}
                          >
                            {hasWindowAt(section + 1, col) ? '☐' : ''}
                          </button>
                        ))}
                        <span className="text-xs text-gray-400 ml-1 self-center">S{section + 1}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Step 2: Glass Pane Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              2. Glass Pane Type
            </label>
            <div className="grid grid-cols-2 gap-3">
              {glassPaneOptions.map((option) => (
                <button
                  key={option.id}
                  onClick={() => onChange({ glassPaneType: option.id })}
                  className={`p-4 rounded-lg border-2 text-left transition-all ${
                    door.glassPaneType === option.id
                      ? 'border-indigo-500 bg-indigo-50'
                      : 'border-gray-200 hover:border-gray-400'
                  }`}
                >
                  <span className="block font-medium text-gray-900">{option.name}</span>
                  <span className="block text-xs text-gray-500 mt-1">{option.description}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Step 3: Glass Color */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              3. Glass Color
            </label>
            <div className="grid grid-cols-3 gap-3">
              {glassColorOptions.map((option) => (
                <button
                  key={option.id}
                  onClick={() => onChange({ glassColor: option.id })}
                  className={`p-3 rounded-lg border-2 flex flex-col items-center transition-all ${
                    door.glassColor === option.id
                      ? 'border-indigo-500 bg-indigo-50'
                      : 'border-gray-200 hover:border-gray-400'
                  }`}
                >
                  {/* Glass color preview */}
                  <div
                    className="w-16 h-10 rounded border border-gray-300 mb-2"
                    style={{ backgroundColor: option.color }}
                  />
                  <span className="font-medium text-gray-900 text-sm">{option.name}</span>
                  <span className="text-xs text-gray-500 text-center">{option.description}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Step 4: Optional Window Inserts */}
          <div className="border-t pt-6">
            <div className="flex items-center space-x-3 mb-4">
              <input
                type="checkbox"
                id="hasInserts"
                checked={door.hasInserts || false}
                onChange={(e) => onChange({
                  hasInserts: e.target.checked,
                  windowInsert: e.target.checked ? 'STOCKTON_STANDARD' : 'NONE'
                })}
                className="h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded"
              />
              <label htmlFor="hasInserts" className="text-sm font-medium text-gray-700">
                Add decorative window inserts (optional upgrade)
              </label>
            </div>

            {door.hasInserts && (
              <div className="pl-7">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  4. Select Insert Style
                </label>
                <div className="space-y-4">
                  {Object.entries(windowInserts).map(([style, inserts]) => (
                    <div key={style}>
                      <h4 className="text-sm font-medium text-gray-600 mb-2">{style}</h4>
                      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
                        {inserts.map((insert) => (
                          <button
                            key={insert.id}
                            onClick={() => onChange({ windowInsert: insert.id })}
                            className={`p-2 rounded-lg border-2 flex flex-col items-center transition-all ${
                              door.windowInsert === insert.id
                                ? 'border-indigo-500 bg-indigo-50'
                                : 'border-gray-200 hover:border-gray-400'
                            }`}
                          >
                            <WindowInsertPreview insertId={insert.id} size={60} />
                            <span className="mt-2 text-xs text-center text-gray-700 leading-tight">
                              {insert.name}
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function HardwareStep({ door, trackOptions, hardwareOptions, operatorOptions, onChange }) {
  const operators = operatorOptions[door.doorType] || operatorOptions.residential

  // Spring cycle options
  const springCycleOptions = [
    { id: 10000, name: '10,000 cycles', description: 'Standard residential' },
    { id: 15000, name: '15,000 cycles', description: 'Extended life' },
    { id: 25000, name: '25,000 cycles', description: 'Commercial light duty' },
    { id: 50000, name: '50,000 cycles', description: 'Commercial standard' },
    { id: 100000, name: '100,000 cycles', description: 'High cycle commercial' },
  ]

  // Shaft type options - auto-detect based on width (14'2" = 170")
  const shaftTypeOptions = [
    { id: 'auto', name: 'Auto (Recommended)', description: door.doorWidth <= 170 ? 'Single shaft (≤14\'2")' : 'Split shaft with coupler (>14\'2")' },
    { id: 'single', name: 'Single Shaft', description: 'No coupler - up to 14\'2" wide' },
    { id: 'split', name: 'Split Shaft', description: 'Two pieces with coupler' },
  ]

  // Warn if single shaft selected for wide door
  const shaftWarning = door.shaftType === 'single' && door.doorWidth > 170

  // Determine allowed track thickness based on selected radius
  const selectedRadius = trackOptions.radius?.find(r => r.id === door.trackRadius)
  const allowedThickness = selectedRadius?.allowedThickness || ['2', '3']
  const isLowHeadroom = door.liftType === 'low_headroom'

  // Handle radius change - auto-correct track thickness if needed
  const handleRadiusChange = (radiusId) => {
    const radius = trackOptions.radius?.find(r => r.id === radiusId)
    const allowed = radius?.allowedThickness || ['2', '3']
    const updates = { trackRadius: radiusId }
    // If current thickness is not allowed for new radius, switch to first allowed
    if (!allowed.includes(door.trackThickness)) {
      updates.trackThickness = allowed[0]
    }
    onChange(updates)
  }

  // Handle lift type change - enforce constraints
  const handleLiftTypeChange = (liftTypeId) => {
    const liftOption = trackOptions.liftType?.find(lt => lt.id === liftTypeId)
    const updates = { liftType: liftTypeId }
    // Low headroom forces 2" track
    if (liftOption?.forcedTrackSize) {
      updates.trackThickness = String(liftOption.forcedTrackSize)
    }
    onChange(updates)
  }

  return (
    <div className="space-y-6">
      {/* Lift Type */}
      {trackOptions.liftType && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Lift Type
          </label>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {trackOptions.liftType.map((option) => (
              <button
                key={option.id}
                onClick={() => handleLiftTypeChange(option.id)}
                className={`p-3 rounded-lg border-2 text-center transition-all ${
                  door.liftType === option.id
                    ? 'border-indigo-500 bg-indigo-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <div className="text-sm font-medium">{option.name}</div>
                <div className="text-xs text-gray-500 mt-1">{option.description}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Track Configuration - only show radius/thickness for standard lift */}
      {door.liftType === 'standard' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Track Radius
            </label>
            <div className="space-y-2">
              {trackOptions.radius.map((option) => (
                <label key={option.id} className="flex items-center">
                  <input
                    type="radio"
                    name="trackRadius"
                    value={option.id}
                    checked={door.trackRadius === option.id}
                    onChange={(e) => handleRadiusChange(e.target.value)}
                    className="h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300"
                  />
                  <span className="ml-2 text-sm text-gray-700">
                    {option.name}
                    {option.note && <span className="text-xs text-amber-600 ml-1">({option.note})</span>}
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Track Thickness
            </label>
            <div className="space-y-2">
              {trackOptions.thickness.map((option) => {
                const isDisabled = !allowedThickness.includes(option.id)
                return (
                  <label key={option.id} className={`flex items-center ${isDisabled ? 'opacity-40 cursor-not-allowed' : ''}`}>
                    <input
                      type="radio"
                      name="trackThickness"
                      value={option.id}
                      checked={door.trackThickness === option.id}
                      onChange={(e) => onChange({ trackThickness: e.target.value })}
                      disabled={isDisabled}
                      className="h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300"
                    />
                    <span className="ml-2 text-sm text-gray-700">
                      {option.name}
                      {isDisabled && <span className="text-xs text-red-500 ml-1">(not available with {door.trackRadius}" radius)</span>}
                    </span>
                  </label>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* Low headroom info */}
      {isLowHeadroom && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
          <p className="text-sm text-blue-800">
            <span className="font-medium">2" Double Track Low Headroom</span> - Uses 2" track with double track configuration for minimal headroom clearance.
          </p>
        </div>
      )}

      {/* Spring Cycles */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Spring Cycle Life
        </label>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {springCycleOptions.map((option) => (
            <button
              key={option.id}
              onClick={() => onChange({ targetCycles: option.id })}
              className={`p-3 rounded-lg border-2 text-center transition-all ${
                door.targetCycles === option.id
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <span className="block text-sm font-medium text-gray-900">{option.name}</span>
              <span className="block text-xs text-gray-500">{option.description}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Shaft Type */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Shaft Configuration
        </label>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {shaftTypeOptions.map((option) => (
            <button
              key={option.id}
              onClick={() => onChange({ shaftType: option.id })}
              className={`p-3 rounded-lg border-2 text-left transition-all ${
                door.shaftType === option.id
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <span className="block text-sm font-medium text-gray-900">{option.name}</span>
              <span className="block text-xs text-gray-500">{option.description}</span>
            </button>
          ))}
        </div>
        {shaftWarning && (
          <div className="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded-md">
            <p className="text-xs text-yellow-700">
              Warning: Single shaft is only recommended for doors up to 14'2" wide. Your door is {Math.floor(door.doorWidth / 12)}'{door.doorWidth % 12}".
            </p>
          </div>
        )}
      </div>

      {/* Hardware Options */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Hardware Components
        </label>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {hardwareOptions.map((option) => (
            <label key={option.id} className="flex items-start p-3 border rounded-lg cursor-pointer hover:bg-gray-50">
              <input
                type="checkbox"
                checked={door.hardware[option.id] !== false}
                onChange={(e) => onChange({
                  hardware: { ...door.hardware, [option.id]: e.target.checked }
                })}
                className="h-4 w-4 mt-0.5 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded"
              />
              <div className="ml-2">
                <span className="text-sm font-medium text-gray-700">{option.name}</span>
                <p className="text-xs text-gray-500">{option.description}</p>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Operator */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Door Operator
        </label>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {operators.map((op) => (
            <button
              key={op.id}
              onClick={() => onChange({ operator: op.id })}
              className={`p-4 rounded-lg border-2 text-left transition-all ${
                door.operator === op.id
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <h4 className="font-medium text-gray-900">{op.name}</h4>
              {op.hp && <p className="mt-1 text-xs text-gray-500">{op.hp}</p>}
              {op.features && (
                <p className="mt-1 text-xs text-gray-400">{op.features.join(', ')}</p>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function ReviewStep({ doors, config, onGenerateQuote, isGenerating, quoteResult }) {
  const [partsData, setPartsData] = useState(null)
  const [loadingParts, setLoadingParts] = useState(false)
  const [showParts, setShowParts] = useState(false)
  const [calculations, setCalculations] = useState([])
  const [loadingCalcs, setLoadingCalcs] = useState(false)
  const [showCalcs, setShowCalcs] = useState(true)

  // Fetch part numbers and calculations when component mounts or doors change
  useEffect(() => {
    async function fetchData() {
      if (!doors.length || !doors[0].doorSeries) return

      setLoadingParts(true)
      setLoadingCalcs(true)

      // Fetch parts
      try {
        const request = {
          doors: doors.map(door => ({
            doorType: door.doorType,
            doorSeries: door.doorSeries,
            doorWidth: door.doorWidth,
            doorHeight: door.doorHeight,
            doorCount: door.doorCount,
            panelColor: door.panelColor,
            panelDesign: door.panelDesign,
            // Window configuration
            hasWindows: door.hasWindows || false,
            windowPositions: door.windowPositions || [],
            glassPaneType: door.glassPaneType,
            glassColor: door.glassColor,
            hasInserts: door.hasInserts || false,
            windowInsert: door.hasInserts && door.windowInsert !== 'NONE' ? door.windowInsert : null,
            windowSection: door.windowSection,
            glazingType: door.glazingType !== 'NONE' ? door.glazingType : null,
            trackRadius: door.trackRadius,
            trackThickness: door.liftType === 'low_headroom' ? '2' : door.trackThickness,
            liftType: door.liftType,
            hardware: door.hardware,
            operator: door.operator !== 'NONE' ? door.operator : null,
          }))
        }
        const response = await doorConfigApi.getPartsForQuote(request)
        if (response.data.success) {
          setPartsData(response.data.data)
        }
      } catch (error) {
        console.error('Error fetching parts:', error)
      } finally {
        setLoadingParts(false)
      }

      // Fetch calculations for each door (commercial doors only)
      try {
        const calcPromises = doors
          .filter(door => ['TX450', 'TX500', 'TX450-20', 'TX500-20', 'TX380'].includes(door.doorSeries))
          .map(async (door) => {
            const calcRequest = {
              doorModel: door.doorSeries,
              widthFeet: Math.floor(door.doorWidth / 12),
              widthInches: door.doorWidth % 12,
              heightFeet: Math.floor(door.doorHeight / 12),
              heightInches: door.doorHeight % 12,
              liftType: door.liftType === 'low_headroom' ? 'low_headroom'
                : door.liftType === 'high_lift' ? 'high_lift'
                : door.liftType === 'vertical' ? 'vertical'
                : door.trackRadius === '12' ? 'standard_12' : 'standard_15',
              trackSize: door.liftType === 'low_headroom' ? 2 : parseInt(door.trackThickness),
              windowType: door.windowInsert !== 'NONE' ? '24x12' : null,
              windowQty: door.windowInsert !== 'NONE' ? 1 : 0,
              doubleEndCaps: false,
              heavyDutyHinges: false,
              targetCycles: door.targetCycles || 10000,
              shaftType: door.shaftType || 'auto',
            }
            const response = await doorConfigApi.calculateDoor(calcRequest)
            return {
              door: door,
              calculation: response.data.success ? response.data.data : null
            }
          })

        const results = await Promise.all(calcPromises)
        setCalculations(results)
      } catch (error) {
        console.error('Error fetching calculations:', error)
      } finally {
        setLoadingCalcs(false)
      }
    }
    fetchData()
  }, [doors])

  function getSeriesName(doorType, seriesId) {
    const series = config?.doorSeries[doorType]?.find(s => s.id === seriesId)
    return series?.name || seriesId
  }

  function getColorName(seriesId, colorId) {
    const colorMap = {
      'KANATA': 'KANATA',
      'CRAFT': 'CRAFT',
      'TX450': 'COMMERCIAL',
      'TX500': 'COMMERCIAL',
      'AL976': 'AL976',
    }
    const colorKey = colorMap[seriesId] || 'KANATA'
    const color = config?.colors[colorKey]?.find(c => c.id === colorId)
    return color?.name || colorId
  }

  return (
    <div className="space-y-6">
      <div className="bg-gray-50 rounded-lg p-4">
        <h3 className="font-medium text-gray-900 mb-4">Configuration Summary</h3>

        {doors.map((door, index) => (
          <div key={index} className="mb-6 last:mb-0">
            <h4 className="text-sm font-medium text-indigo-600 mb-2">
              Door {index + 1} {door.doorCount > 1 && `(Qty: ${door.doorCount})`}
            </h4>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <span className="text-gray-500">Type:</span>
                <span className="ml-2 text-gray-900 capitalize">{door.doorType}</span>
              </div>
              <div>
                <span className="text-gray-500">Series:</span>
                <span className="ml-2 text-gray-900">{getSeriesName(door.doorType, door.doorSeries)}</span>
              </div>
              <div>
                <span className="text-gray-500">Size:</span>
                <span className="ml-2 text-gray-900">
                  {Math.floor(door.doorWidth / 12)}'{door.doorWidth % 12}" × {Math.floor(door.doorHeight / 12)}'{door.doorHeight % 12}"
                </span>
              </div>
              <div>
                <span className="text-gray-500">Color:</span>
                <span className="ml-2 text-gray-900">{getColorName(door.doorSeries, door.panelColor)}</span>
              </div>
              <div>
                <span className="text-gray-500">Design:</span>
                <span className="ml-2 text-gray-900">{door.panelDesign}</span>
              </div>
              <div>
                <span className="text-gray-500">Windows:</span>
                <span className="ml-2 text-gray-900">
                  {door.hasWindows && door.windowPositions?.length > 0
                    ? `${door.windowPositions.length} window${door.windowPositions.length > 1 ? 's' : ''}`
                    : 'No'}
                </span>
              </div>
              {door.hasWindows && (
                <>
                  <div>
                    <span className="text-gray-500">Glass:</span>
                    <span className="ml-2 text-gray-900">
                      {door.glassPaneType === 'INSULATED' ? 'Insulated' : 'Single'}, {door.glassColor || 'Clear'}
                    </span>
                  </div>
                  {door.hasInserts && (
                    <div>
                      <span className="text-gray-500">Inserts:</span>
                      <span className="ml-2 text-gray-900">{door.windowInsert}</span>
                    </div>
                  )}
                </>
              )}
              <div>
                <span className="text-gray-500">Track:</span>
                <span className="ml-2 text-gray-900">
                  {door.liftType === 'low_headroom'
                    ? '2" Double Track Low Headroom'
                    : `${door.trackRadius}" radius / ${door.trackThickness}" track`}
                  {door.liftType === 'high_lift' && ' (High Lift)'}
                  {door.liftType === 'vertical' && ' (Vertical Lift)'}
                </span>
              </div>
              <div>
                <span className="text-gray-500">Operator:</span>
                <span className="ml-2 text-gray-900">{door.operator === 'NONE' ? 'None' : door.operator}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Door Calculations Section */}
      {calculations.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg">
          <button
            onClick={() => setShowCalcs(!showCalcs)}
            className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-50"
          >
            <div className="flex items-center">
              <svg className="h-5 w-5 text-gray-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </svg>
              <span className="font-medium text-gray-900">Door Specifications</span>
              <span className="ml-2 text-sm text-gray-500">
                (Weight, Springs, Drums, Hardware)
              </span>
            </div>
            <svg
              className={`h-5 w-5 text-gray-500 transform transition-transform ${showCalcs ? 'rotate-180' : ''}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showCalcs && (
            <div className="px-4 pb-4 border-t border-gray-200">
              {loadingCalcs ? (
                <div className="py-4 text-center text-gray-500">Calculating specifications...</div>
              ) : (
                <div className="mt-4 space-y-6">
                  {calculations.map((item, idx) => (
                    <div key={idx} className="bg-gray-50 rounded-lg p-4">
                      <h4 className="font-medium text-indigo-600 mb-3">
                        {item.door.doorSeries} - {Math.floor(item.door.doorWidth / 12)}' x {Math.floor(item.door.doorHeight / 12)}'
                      </h4>

                      {item.calculation && (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                          {/* Weight Summary */}
                          <div className="bg-white rounded-lg p-3 shadow-sm">
                            <h5 className="text-sm font-medium text-gray-700 mb-2">Weight Breakdown</h5>
                            <div className="space-y-1 text-sm">
                              <div className="flex justify-between">
                                <span className="text-gray-500">Steel:</span>
                                <span className="font-medium">{item.calculation.weight?.steel_lbs?.toFixed(1)} lbs</span>
                              </div>
                              <div className="flex justify-between">
                                <span className="text-gray-500">Hardware:</span>
                                <span className="font-medium">{item.calculation.weight?.hardware_lbs?.toFixed(1)} lbs</span>
                              </div>
                              {item.calculation.weight?.strut_lbs > 0 && (
                                <div className="flex justify-between">
                                  <span className="text-gray-500">
                                    Struts{item.calculation.hardware?.z_strut_lengths ? ' (Z)' : ''}:
                                  </span>
                                  <span className="font-medium">{item.calculation.weight?.strut_lbs?.toFixed(1)} lbs</span>
                                </div>
                              )}
                              {item.calculation.weight?.glazing_lbs > 0 && (
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Glazing:</span>
                                  <span className="font-medium">{item.calculation.weight?.glazing_lbs?.toFixed(1)} lbs</span>
                                </div>
                              )}
                              <div className="flex justify-between border-t pt-1 mt-1">
                                <span className="text-gray-700 font-medium">Total:</span>
                                <span className="font-bold text-indigo-600">{item.calculation.weight?.total_lbs?.toFixed(1)} lbs</span>
                              </div>
                              {item.calculation.hardware?.z_strut_lengths && (
                                <div className="mt-2 pt-2 border-t border-dashed text-xs text-gray-500">
                                  Z Strut: {item.calculation.hardware.z_strut_lengths.map(l => `${l/12}'`).join(' + ')} per strut
                                </div>
                              )}
                            </div>
                          </div>

                          {/* Panel Configuration */}
                          <div className="bg-white rounded-lg p-3 shadow-sm">
                            <h5 className="text-sm font-medium text-gray-700 mb-2">Panel Configuration</h5>
                            <div className="space-y-1 text-sm">
                              <div className="flex justify-between">
                                <span className="text-gray-500">Total Sections:</span>
                                <span className="font-medium">{item.calculation.panels?.total_sections}</span>
                              </div>
                              <div className="flex justify-between">
                                <span className="text-gray-500">21" Sections:</span>
                                <span className="font-medium">{item.calculation.panels?.sections_21_inch}</span>
                              </div>
                              <div className="flex justify-between">
                                <span className="text-gray-500">24" Sections:</span>
                                <span className="font-medium">{item.calculation.panels?.sections_24_inch}</span>
                              </div>
                              <div className="flex justify-between">
                                <span className="text-gray-500">Gauge:</span>
                                <span className="font-medium">{item.calculation.panels?.gauge}ga</span>
                              </div>
                            </div>
                          </div>

                          {/* Springs */}
                          {item.calculation.springs && (
                            <div className="bg-white rounded-lg p-3 shadow-sm">
                              <h5 className="text-sm font-medium text-gray-700 mb-2">
                                Spring Specifications
                                {item.calculation.springs.is_duplex && (
                                  <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800">
                                    DUPLEX
                                  </span>
                                )}
                              </h5>
                              <div className="space-y-1 text-sm">
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Total Springs:</span>
                                  <span className="font-medium">
                                    {item.calculation.springs.quantity}
                                    {item.calculation.springs.is_duplex && (
                                      <span className="text-gray-400 text-xs ml-1">
                                        ({item.calculation.springs.duplex_pairs} duplex pairs)
                                      </span>
                                    )}
                                  </span>
                                </div>
                                {item.calculation.springs.is_duplex ? (
                                  <>
                                    <div className="mt-2 pt-2 border-t border-gray-100">
                                      <span className="text-xs font-medium text-gray-600">Outer Spring (6" coil):</span>
                                    </div>
                                    <div className="flex justify-between pl-2">
                                      <span className="text-gray-500">Wire:</span>
                                      <span className="font-medium">{item.calculation.springs.wire_diameter}"</span>
                                    </div>
                                    <div className="flex justify-between pl-2">
                                      <span className="text-gray-500">Length:</span>
                                      <span className="font-medium">{item.calculation.springs.length}"</span>
                                    </div>
                                    <div className="mt-1 pt-1 border-t border-gray-100">
                                      <span className="text-xs font-medium text-gray-600">Inner Spring (3-3/4" coil):</span>
                                    </div>
                                    <div className="flex justify-between pl-2">
                                      <span className="text-gray-500">Wire:</span>
                                      <span className="font-medium">{item.calculation.springs.inner_wire_diameter}"</span>
                                    </div>
                                    <div className="flex justify-between pl-2">
                                      <span className="text-gray-500">Length:</span>
                                      <span className="font-medium">{item.calculation.springs.inner_length}"</span>
                                    </div>
                                  </>
                                ) : (
                                  <>
                                    <div className="flex justify-between">
                                      <span className="text-gray-500">Coil Diameter:</span>
                                      <span className="font-medium">{item.calculation.springs.coil_diameter}"</span>
                                    </div>
                                    <div className="flex justify-between">
                                      <span className="text-gray-500">Wire Diameter:</span>
                                      <span className="font-medium">{item.calculation.springs.wire_diameter}"</span>
                                    </div>
                                    <div className="flex justify-between">
                                      <span className="text-gray-500">Length:</span>
                                      <span className="font-medium">{item.calculation.springs.length}"</span>
                                    </div>
                                  </>
                                )}
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Cycles:</span>
                                  <span className="font-medium">{item.calculation.springs.cycles?.toLocaleString()}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Turns:</span>
                                  <span className="font-medium">{item.calculation.springs.turns}</span>
                                </div>
                              </div>
                            </div>
                          )}

                          {/* Drum */}
                          {item.calculation.drum && (
                            <div className="bg-white rounded-lg p-3 shadow-sm">
                              <h5 className="text-sm font-medium text-gray-700 mb-2">Drum & Cable</h5>
                              <div className="space-y-1 text-sm">
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Drum Model:</span>
                                  <span className="font-medium font-mono">{item.calculation.drum.model}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Offset:</span>
                                  <span className="font-medium">{item.calculation.drum.offset}"</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Cable Diameter:</span>
                                  <span className="font-medium">{item.calculation.drum.cable_diameter}"</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Cable Length:</span>
                                  <span className="font-medium">{item.calculation.drum.cable_length}"</span>
                                </div>
                              </div>
                            </div>
                          )}

                          {/* Shaft */}
                          {item.calculation.shaft && (
                            <div className="bg-white rounded-lg p-3 shadow-sm">
                              <h5 className="text-sm font-medium text-gray-700 mb-2">Shaft Configuration</h5>
                              <div className="space-y-1 text-sm">
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Diameter:</span>
                                  <span className="font-medium">{item.calculation.shaft.diameter}"</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Length (each):</span>
                                  <span className="font-medium">{item.calculation.shaft.length_each}"</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Pieces:</span>
                                  <span className="font-medium">{item.calculation.shaft.pieces}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Couplers:</span>
                                  <span className="font-medium">{item.calculation.shaft.couplers}</span>
                                </div>
                              </div>
                            </div>
                          )}

                          {/* Track */}
                          {item.calculation.track && (
                            <div className="bg-white rounded-lg p-3 shadow-sm">
                              <h5 className="text-sm font-medium text-gray-700 mb-2">Track Configuration</h5>
                              <div className="space-y-1 text-sm">
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Size:</span>
                                  <span className="font-medium">{item.calculation.track.size_inches}"</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Radius:</span>
                                  <span className="font-medium">{item.calculation.track.radius}"</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Vertical Length:</span>
                                  <span className="font-medium">{item.calculation.track.vertical_length}"</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-gray-500">Horizontal Length:</span>
                                  <span className="font-medium">{item.calculation.track.horizontal_length}"</span>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {item.calculation?.warnings?.length > 0 && (
                        <div className="mt-3 bg-yellow-50 border border-yellow-200 rounded p-2">
                          <p className="text-xs text-yellow-700">
                            {item.calculation.warnings.join(', ')}
                          </p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Part Numbers Section */}
      <div className="bg-white border border-gray-200 rounded-lg">
        <button
          onClick={() => setShowParts(!showParts)}
          className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-50"
        >
          <div className="flex items-center">
            <svg className="h-5 w-5 text-gray-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            <span className="font-medium text-gray-900">BC Part Numbers</span>
            {partsData && (
              <span className="ml-2 text-sm text-gray-500">
                ({partsData.total_unique_parts} parts)
              </span>
            )}
          </div>
          <svg
            className={`h-5 w-5 text-gray-500 transform transition-transform ${showParts ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {showParts && (
          <div className="px-4 pb-4 border-t border-gray-200">
            {loadingParts ? (
              <div className="py-4 text-center text-gray-500">Loading part numbers...</div>
            ) : partsData ? (
              <div className="mt-4 space-y-4">
                {/* Consolidated Parts List */}
                <div>
                  <h4 className="text-sm font-medium text-gray-700 mb-2">Consolidated Parts List</h4>
                  <div className="bg-gray-50 rounded-lg overflow-hidden">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-100">
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Part #</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                          <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase">Qty</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Category</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-200">
                        {partsData.consolidated_parts?.map((part, idx) => (
                          <tr key={idx} className="hover:bg-gray-100">
                            <td className="px-3 py-2 text-sm font-mono text-indigo-600">{part.part_number}</td>
                            <td className="px-3 py-2 text-sm text-gray-900">{part.description}</td>
                            <td className="px-3 py-2 text-sm text-center text-gray-700">{part.quantity}</td>
                            <td className="px-3 py-2 text-sm text-gray-500 capitalize">{part.category}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Parts by Door (collapsible) */}
                {partsData.parts_by_door?.length > 1 && (
                  <details className="mt-4">
                    <summary className="text-sm font-medium text-gray-700 cursor-pointer hover:text-indigo-600">
                      View parts by door
                    </summary>
                    <div className="mt-2 space-y-3">
                      {partsData.parts_by_door.map((doorParts, idx) => (
                        <div key={idx} className="bg-gray-50 rounded p-3">
                          <h5 className="text-sm font-medium text-indigo-600 mb-2">
                            Door {doorParts.door_index}: {doorParts.door_description}
                          </h5>
                          <ul className="text-xs space-y-1">
                            {doorParts.parts?.parts_list?.map((part, pIdx) => (
                              <li key={pIdx} className="flex justify-between">
                                <span className="font-mono">{part.part_number}</span>
                                <span className="text-gray-500">x{part.quantity}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </details>
                )}

                <p className="text-xs text-gray-400 mt-2">
                  Part numbers are generated based on configuration rules. Verify with BC catalog before ordering.
                </p>
              </div>
            ) : (
              <div className="py-4 text-center text-gray-500">
                Complete the configuration to see part numbers
              </div>
            )}
          </div>
        )}
      </div>

      {/* Generate Quote Button */}
      <button
        onClick={onGenerateQuote}
        disabled={isGenerating}
        className="w-full inline-flex justify-center items-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isGenerating ? (
          <>
            <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Generating Quote...
          </>
        ) : (
          'Generate Quote'
        )}
      </button>

      {/* Quote Result */}
      {quoteResult && quoteResult.success && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <div className="flex items-center">
            <svg className="h-5 w-5 text-green-400 mr-2" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
            <span className="text-green-800 font-medium">Quote Generated Successfully!</span>
          </div>
          {quoteResult.data && (
            <div className="mt-3 space-y-2">
              <p className="text-sm text-green-700">
                <span className="font-medium">BC Quote #:</span> {quoteResult.data.bc_quote_number}
              </p>
              <p className="text-sm text-green-700">
                <span className="font-medium">Lines Added:</span> {quoteResult.data.lines_added} items
              </p>
              {quoteResult.data.pricing && (
                <div className="mt-3 pt-3 border-t border-green-200">
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <span className="text-green-600">Subtotal:</span>
                    <span className="text-right font-medium">${quoteResult.data.pricing.subtotal?.toLocaleString('en-CA', { minimumFractionDigits: 2 })}</span>
                    <span className="text-green-600">Tax (GST):</span>
                    <span className="text-right font-medium">${quoteResult.data.pricing.tax?.toLocaleString('en-CA', { minimumFractionDigits: 2 })}</span>
                    <span className="text-green-700 font-semibold">Total:</span>
                    <span className="text-right font-bold text-lg text-green-800">${quoteResult.data.pricing.total?.toLocaleString('en-CA', { minimumFractionDigits: 2 })}</span>
                  </div>
                </div>
              )}
              {quoteResult.data.lines_failed && quoteResult.data.lines_failed.length > 0 && (
                <div className="mt-2 text-xs text-yellow-700 bg-yellow-50 p-2 rounded">
                  <span className="font-medium">Note:</span> {quoteResult.data.lines_failed.length} items could not be added (not in BC inventory)
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default DoorConfigurator
