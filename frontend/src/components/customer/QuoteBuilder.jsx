import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { savedQuotesApi, customerDoorConfigApi } from '../../api/customerClient'

const STEPS = [
  { id: 'type', title: 'Door Type', description: 'Select door category' },
  { id: 'series', title: 'Series', description: 'Choose door series' },
  { id: 'dimensions', title: 'Dimensions', description: 'Set size and quantity' },
  { id: 'design', title: 'Design', description: 'Color and panel style' },
  { id: 'windows', title: 'Windows', description: 'Window configuration' },
  { id: 'hardware', title: 'Hardware', description: 'Track and hardware' },
  { id: 'review', title: 'Review', description: 'Review and save' },
]

function QuoteBuilder() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isEditing = !!id

  const [quoteName, setQuoteName] = useState('')
  const [quoteDescription, setQuoteDescription] = useState('')
  const [currentStep, setCurrentStep] = useState(0)
  const [doors, setDoors] = useState([createEmptyDoor()])
  const [currentDoorIndex, setCurrentDoorIndex] = useState(0)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  // Fetch existing quote if editing
  const { data: existingQuote, isLoading: loadingQuote } = useQuery({
    queryKey: ['savedQuote', id],
    queryFn: async () => {
      const response = await savedQuotesApi.get(id)
      return response.data
    },
    enabled: isEditing
  })

  // Fetch full configuration options from API
  const { data: config, isLoading: configLoading } = useQuery({
    queryKey: ['doorConfig'],
    queryFn: async () => {
      const response = await customerDoorConfigApi.getFullConfig()
      return response.data.data
    },
  })

  // Load existing quote data
  useEffect(() => {
    if (existingQuote) {
      setQuoteName(existingQuote.name || '')
      setQuoteDescription(existingQuote.description || '')
      if (existingQuote.config_data?.doors) {
        setDoors(existingQuote.config_data.doors)
      } else if (existingQuote.config_data) {
        // Legacy single door format
        setDoors([{
          ...createEmptyDoor(),
          doorType: existingQuote.config_data.door_type || '',
          doorWidth: existingQuote.config_data.width || 96,
          doorHeight: existingQuote.config_data.height || 84,
          panelColor: existingQuote.config_data.color || '',
          windowInsert: existingQuote.config_data.window_type === 'none' ? 'NONE' : existingQuote.config_data.window_type || 'NONE',
        }])
      }
    }
  }, [existingQuote])

  function createEmptyDoor() {
    return {
      doorType: '',
      doorSeries: '',
      doorWidth: 96,
      doorHeight: 84,
      doorCount: 1,
      panelColor: '',
      panelDesign: '',
      windowInsert: 'NONE',
      windowSection: 1,
      glazingType: 'NONE',
      trackRadius: '15',
      trackThickness: '2',
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
        return !!quoteName.trim()
      default:
        return true
    }
  }

  const saveMutation = useMutation({
    mutationFn: async (data) => {
      if (isEditing) {
        return savedQuotesApi.update(id, data)
      }
      return savedQuotesApi.create(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['savedQuotes'])
      navigate('/saved-quotes')
    }
  })

  async function handleSave() {
    if (!quoteName.trim()) {
      setErrors({ name: 'Quote name is required' })
      return
    }

    setErrors({})
    setSaving(true)

    try {
      await saveMutation.mutateAsync({
        name: quoteName.trim(),
        description: quoteDescription.trim(),
        config_data: { doors }
      })
    } catch (error) {
      console.error('Save error:', error)
      setErrors({ submit: error.response?.data?.detail || 'Failed to save quote' })
    } finally {
      setSaving(false)
    }
  }

  if (configLoading || loadingQuote) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        <span className="ml-3 text-gray-500">Loading configuration...</span>
      </div>
    )
  }

  if (isEditing && existingQuote?.is_submitted) {
    return (
      <div className="bg-yellow-50 p-6 rounded-lg">
        <h2 className="text-lg font-medium text-yellow-800">Quote Already Submitted</h2>
        <p className="mt-2 text-yellow-700">
          This quote has been submitted and cannot be edited.
          {existingQuote.bc_quote_number && ` BC Quote: ${existingQuote.bc_quote_number}`}
        </p>
        <button
          onClick={() => navigate('/saved-quotes')}
          className="mt-4 text-blue-600 hover:text-blue-500"
        >
          Back to quotes
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex justify-between items-start">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              {isEditing ? 'Edit Quote' : 'New Door Quote'}
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              Configure your door step by step
            </p>
          </div>
          <button
            onClick={() => navigate('/saved-quotes')}
            className="text-gray-500 hover:text-gray-700"
          >
            Cancel
          </button>
        </div>
      </div>

      {/* Door Tabs */}
      {doors.length > 0 && (
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
                    ? 'bg-blue-100 text-blue-700'
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
                        ? 'bg-blue-600 hover:bg-blue-800'
                        : index === currentStep
                        ? 'border-2 border-blue-600 bg-white'
                        : 'border-2 border-gray-300 bg-white'
                    }`}
                  >
                    {index < currentStep ? (
                      <svg className="h-5 w-5 text-white" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    ) : (
                      <span className={index === currentStep ? 'text-blue-600' : 'text-gray-500'}>
                        {index + 1}
                      </span>
                    )}
                  </button>
                  {index !== STEPS.length - 1 && (
                    <div className={`absolute top-4 w-full h-0.5 ${index < currentStep ? 'bg-blue-600' : 'bg-gray-300'}`} style={{ left: '2rem' }} />
                  )}
                </div>
                <div className="mt-2 hidden sm:block">
                  <span className={`text-xs font-medium ${index <= currentStep ? 'text-blue-600' : 'text-gray-500'}`}>
                    {step.title}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        </nav>
      </div>

      {/* Error Display */}
      {errors.submit && (
        <div className="bg-red-50 p-4 rounded-md">
          <p className="text-red-700">{errors.submit}</p>
        </div>
      )}

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

        {/* Step 7: Review */}
        {STEPS[currentStep].id === 'review' && (
          <ReviewStep
            doors={doors}
            config={config}
            quoteName={quoteName}
            quoteDescription={quoteDescription}
            onNameChange={setQuoteName}
            onDescriptionChange={setQuoteDescription}
            onSave={handleSave}
            isSaving={saving}
            errors={errors}
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
          Previous
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
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Next
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
      {doorTypes?.map((type) => (
        <button
          key={type.id}
          onClick={() => onSelect(type.id)}
          className={`p-4 rounded-lg border-2 text-left transition-all ${
            selected === type.id
              ? 'border-blue-500 bg-blue-50'
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
              ? 'border-blue-500 bg-blue-50'
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
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
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
            className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-blue-500 focus:border-blue-500"
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
            className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-blue-500 focus:border-blue-500"
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
            className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-blue-500 focus:border-blue-500"
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
  const availableColors = colors?.[colorKey] || colors?.['KANATA'] || []

  // Get panel designs for current series
  const designMap = {
    'KANATA': 'KANATA',
    'CRAFT': 'CRAFT',
    'KANATA_EXECUTIVE': 'EXECUTIVE',
  }
  const designKey = designMap[door.doorSeries] || 'KANATA'
  const availableDesigns = panelDesigns?.[designKey] || []

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
                  ? 'border-blue-500 ring-2 ring-blue-200'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div
                className="w-8 h-8 rounded-full mx-auto border border-gray-300"
                style={{ backgroundColor: color.hex || '#ccc' }}
              />
              <span className="mt-1 block text-xs text-gray-700">{color.name}</span>
              {color.note && <span className="text-xs text-gray-400">{color.note}</span>}
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
                  ? 'border-blue-500 bg-blue-50'
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

function WindowsStep({ door, windowInserts, glazingOptions, onChange }) {
  const hasWindows = door.windowInsert !== 'NONE' && door.windowInsert

  // Calculate panel count based on height
  const panelCount = door.doorHeight <= 84 ? 4 : door.doorHeight <= 96 ? 5 : 6

  return (
    <div className="space-y-6">
      {/* Window Toggle */}
      <div className="flex items-center space-x-3">
        <input
          type="checkbox"
          id="hasWindows"
          checked={hasWindows}
          onChange={(e) => onChange({ windowInsert: e.target.checked ? 'STOCKTON_STANDARD' : 'NONE' })}
          className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
        />
        <label htmlFor="hasWindows" className="text-sm font-medium text-gray-700">
          Include windows in this door
        </label>
      </div>

      {hasWindows && (
        <>
          {/* Window Style */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Window Insert Style
            </label>
            <div className="space-y-4">
              {windowInserts && Object.entries(windowInserts).map(([style, inserts]) => (
                <div key={style}>
                  <h4 className="text-sm font-medium text-gray-600 mb-2">{style}</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    {inserts.map((insert) => (
                      <button
                        key={insert.id}
                        onClick={() => onChange({ windowInsert: insert.id })}
                        className={`px-3 py-2 text-sm rounded-md border ${
                          door.windowInsert === insert.id
                            ? 'border-blue-500 bg-blue-50 text-blue-700'
                            : 'border-gray-300 hover:border-gray-400'
                        }`}
                      >
                        {insert.name}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Window Section */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Window Section (1 = Top)
            </label>
            <div className="flex space-x-2">
              {[...Array(panelCount)].map((_, i) => (
                <button
                  key={i + 1}
                  onClick={() => onChange({ windowSection: i + 1 })}
                  className={`w-12 h-12 rounded-md border-2 text-sm font-medium ${
                    door.windowSection === i + 1
                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                      : 'border-gray-300 hover:border-gray-400'
                  }`}
                >
                  {i + 1}
                </button>
              ))}
            </div>
            <p className="mt-1 text-xs text-gray-500">
              This door has {panelCount} panels. Section 1 is the top.
            </p>
          </div>

          {/* Glazing Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Glass Type
            </label>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {(glazingOptions?.[door.doorType] || glazingOptions?.standard || []).map((option) => (
                <button
                  key={option.id}
                  onClick={() => onChange({ glazingType: option.id })}
                  className={`px-3 py-2 text-sm rounded-md border ${
                    door.glazingType === option.id
                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                      : 'border-gray-300 hover:border-gray-400'
                  }`}
                >
                  {option.name}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function HardwareStep({ door, trackOptions, hardwareOptions, operatorOptions, onChange }) {
  const operators = operatorOptions?.[door.doorType] || operatorOptions?.residential || []

  return (
    <div className="space-y-6">
      {/* Track Configuration */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Track Radius
          </label>
          <div className="space-y-2">
            {trackOptions?.radius?.map((option) => (
              <label key={option.id} className="flex items-center">
                <input
                  type="radio"
                  name="trackRadius"
                  value={option.id}
                  checked={door.trackRadius === option.id}
                  onChange={(e) => onChange({ trackRadius: e.target.value })}
                  className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300"
                />
                <span className="ml-2 text-sm text-gray-700">{option.name}</span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Track Thickness
          </label>
          <div className="space-y-2">
            {trackOptions?.thickness?.map((option) => (
              <label key={option.id} className="flex items-center">
                <input
                  type="radio"
                  name="trackThickness"
                  value={option.id}
                  checked={door.trackThickness === option.id}
                  onChange={(e) => onChange({ trackThickness: e.target.value })}
                  className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300"
                />
                <span className="ml-2 text-sm text-gray-700">{option.name}</span>
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* Hardware Options */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Hardware Components
        </label>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {hardwareOptions?.map((option) => (
            <label key={option.id} className="flex items-start p-3 border rounded-lg cursor-pointer hover:bg-gray-50">
              <input
                type="checkbox"
                checked={door.hardware[option.id] !== false}
                onChange={(e) => onChange({
                  hardware: { ...door.hardware, [option.id]: e.target.checked }
                })}
                className="h-4 w-4 mt-0.5 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
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
          Door Operator (Optional)
        </label>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <button
            onClick={() => onChange({ operator: 'NONE' })}
            className={`p-4 rounded-lg border-2 text-left transition-all ${
              door.operator === 'NONE'
                ? 'border-blue-500 bg-blue-50'
                : 'border-gray-200 hover:border-gray-300'
            }`}
          >
            <h4 className="font-medium text-gray-900">No Operator</h4>
            <p className="mt-1 text-xs text-gray-500">Manual operation only</p>
          </button>
          {operators.map((op) => (
            <button
              key={op.id}
              onClick={() => onChange({ operator: op.id })}
              className={`p-4 rounded-lg border-2 text-left transition-all ${
                door.operator === op.id
                  ? 'border-blue-500 bg-blue-50'
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

function ReviewStep({ doors, config, quoteName, quoteDescription, onNameChange, onDescriptionChange, onSave, isSaving, errors }) {
  function getSeriesName(doorType, seriesId) {
    const series = config?.doorSeries?.[doorType]?.find(s => s.id === seriesId)
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
    const color = config?.colors?.[colorKey]?.find(c => c.id === colorId)
    return color?.name || colorId
  }

  return (
    <div className="space-y-6">
      {/* Quote Details */}
      <div className="bg-blue-50 rounded-lg p-4">
        <h3 className="font-medium text-gray-900 mb-4">Quote Details</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Quote Name *
            </label>
            <input
              type="text"
              value={quoteName}
              onChange={(e) => onNameChange(e.target.value)}
              className={`mt-1 block w-full rounded-md shadow-sm sm:text-sm ${
                errors.name ? 'border-red-300' : 'border-gray-300'
              } focus:border-blue-500 focus:ring-blue-500`}
              placeholder="e.g., Main Garage Door"
            />
            {errors.name && <p className="mt-1 text-sm text-red-600">{errors.name}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Description (optional)
            </label>
            <textarea
              value={quoteDescription}
              onChange={(e) => onDescriptionChange(e.target.value)}
              rows={2}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              placeholder="Any additional notes..."
            />
          </div>
        </div>
      </div>

      {/* Configuration Summary */}
      <div className="bg-gray-50 rounded-lg p-4">
        <h3 className="font-medium text-gray-900 mb-4">Configuration Summary</h3>

        {doors.map((door, index) => (
          <div key={index} className="mb-6 last:mb-0">
            <h4 className="text-sm font-medium text-blue-600 mb-2">
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
                <span className="ml-2 text-gray-900">{door.panelDesign || 'Not selected'}</span>
              </div>
              <div>
                <span className="text-gray-500">Windows:</span>
                <span className="ml-2 text-gray-900">
                  {door.windowInsert !== 'NONE' ? `Yes (Section ${door.windowSection})` : 'No'}
                </span>
              </div>
              <div>
                <span className="text-gray-500">Track:</span>
                <span className="ml-2 text-gray-900">{door.trackRadius}" / {door.trackThickness}"</span>
              </div>
              <div>
                <span className="text-gray-500">Operator:</span>
                <span className="ml-2 text-gray-900">{door.operator === 'NONE' ? 'None' : door.operator}</span>
              </div>
            </div>

            {/* Hardware Summary */}
            <div className="mt-3">
              <span className="text-sm text-gray-500">Hardware: </span>
              <span className="text-sm text-gray-700">
                {Object.entries(door.hardware)
                  .filter(([_, v]) => v)
                  .map(([k]) => k.replace(/([A-Z])/g, ' $1').trim())
                  .join(', ')}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Save Button */}
      <button
        onClick={onSave}
        disabled={isSaving || !quoteName.trim()}
        className="w-full inline-flex justify-center items-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isSaving ? (
          <>
            <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Saving...
          </>
        ) : (
          'Save Quote'
        )}
      </button>

      <p className="text-xs text-gray-500 text-center">
        Your quote will be saved as a draft. You can submit it later for processing.
      </p>
    </div>
  )
}

export default QuoteBuilder
