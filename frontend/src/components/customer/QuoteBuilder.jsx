import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { savedQuotesApi, customerDoorConfigApi } from '../../api/customerClient'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'
import DoorPreview from '../DoorPreview'
import DoorDrawings from '../DoorDrawings'
import QuotePricingDisplay from './QuotePricingDisplay'

const STEPS = [
  { id: 'type', title: 'Door Type', description: 'Select door category' },
  { id: 'series', title: 'Series', description: 'Choose door series' },
  { id: 'dimensions', title: 'Dimensions', description: 'Set size and quantity' },
  { id: 'design', title: 'Design', description: 'Color and panel style' },
  { id: 'windows', title: 'Windows', description: 'Window configuration' },
  { id: 'hardware', title: 'Hardware', description: 'Track and hardware' },
  { id: 'drawings', title: 'Drawings', description: 'View and export' },
  { id: 'review', title: 'Review', description: 'Review and save' },
]

function QuoteBuilder() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isEditing = !!id

  const [quoteName, setQuoteName] = useState('')
  const [quoteDescription, setQuoteDescription] = useState('')
  const [poNumber, setPoNumber] = useState('')
  const [deliveryType, setDeliveryType] = useState('')  // '' = not chosen, 'delivery' or 'pickup'
  const [currentStep, setCurrentStep] = useState(0)
  const [doors, setDoors] = useState([createEmptyDoor()])
  const [currentDoorIndex, setCurrentDoorIndex] = useState(0)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [pricingData, setPricingData] = useState(null)
  const [pricingLoading, setPricingLoading] = useState(false)
  const [savedQuoteId, setSavedQuoteId] = useState(id ? parseInt(id) : null)
  const { isBCLinked } = useCustomerAuth()

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
      setDeliveryType(existingQuote.config_data?.deliveryType || '')
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
      // Window configuration
      hasWindows: false,
      windowPositions: [],  // Array of {section, col} for multi-stamp windows
      windowSize: 'long',   // 'short' (GK15-10xxx) or 'long' (GK15-11xxx)
      glassPaneType: null,  // 'INSULATED' or 'SINGLE'
      glassColor: null,  // 'CLEAR', 'ETCHED', 'SUPER_GREY'
      hasInserts: false,  // Whether decorative inserts are added (LONG windows only)
      windowInsert: 'NONE',  // Insert style if hasInserts is true
      windowSection: 1,  // Legacy fallback
      windowQty: 0,  // For commercial doors
      windowFrameColor: 'MATCH',  // 'MATCH' = match door color, or a color ID
      glazingType: 'NONE',  // Legacy
      // Hardware
      trackRadius: '15',
      trackThickness: '2',
      liftType: 'standard',
      hardware: {
        panels: true,
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
      trackMount: 'bracket', // 'bracket' or 'angle'
      // High lift inches (only used for high_lift)
      highLiftInches: null,  // extra inches above door opening
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
      case 'drawings':
        return true // Drawings are view-only
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
        config_data: { doors, poNumber: poNumber || undefined, deliveryType: deliveryType || undefined }
      })
    } catch (error) {
      console.error('Save error:', error)
      setErrors({ submit: error.response?.data?.detail || 'Failed to save quote' })
    } finally {
      setSaving(false)
    }
  }

  async function handleGetPricing() {
    if (!quoteName.trim()) {
      setErrors({ name: 'Quote name is required' })
      return
    }
    if (!deliveryType) {
      setErrors({ delivery: 'Please select Delivery or Pickup before requesting pricing' })
      return
    }

    setErrors({})
    setPricingLoading(true)
    setPricingData(null)

    try {
      // Save the quote first if not yet saved
      let quoteId = savedQuoteId
      if (!quoteId) {
        const saveResponse = await savedQuotesApi.create({
          name: quoteName.trim(),
          description: quoteDescription.trim(),
          config_data: { doors, deliveryType },
        })
        quoteId = saveResponse.data.id
        setSavedQuoteId(quoteId)
      } else {
        // Update existing
        await savedQuotesApi.update(quoteId, {
          name: quoteName.trim(),
          description: quoteDescription.trim(),
          config_data: { doors, deliveryType },
        })
      }

      // Request pricing
      const response = await savedQuotesApi.getPricing(quoteId)
      setPricingData(response.data)
      queryClient.invalidateQueries(['savedQuotes'])
    } catch (error) {
      console.error('Pricing error:', error)
      setErrors({ pricing: error.response?.data?.detail || 'Failed to get pricing' })
    } finally {
      setPricingLoading(false)
    }
  }

  async function handleConfirmSubmit() {
    if (!savedQuoteId || !pricingData) return

    setSaving(true)
    setErrors({})

    try {
      await savedQuotesApi.confirm(savedQuoteId)
      queryClient.invalidateQueries(['savedQuotes'])
      navigate('/saved-quotes')
    } catch (error) {
      console.error('Confirm error:', error)
      setErrors({ submit: error.response?.data?.detail || 'Failed to submit quote' })
    } finally {
      setSaving(false)
    }
  }

  if (configLoading || loadingQuote) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
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
          className="mt-4 text-odc-600 hover:text-odc-500"
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
                    ? 'bg-blue-100 text-odc-700'
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
                        ? 'bg-odc-600 hover:bg-blue-800'
                        : index === currentStep
                        ? 'border-2 border-odc-600 bg-white'
                        : 'border-2 border-gray-300 bg-white'
                    }`}
                  >
                    {index < currentStep ? (
                      <svg className="h-5 w-5 text-white" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    ) : (
                      <span className={index === currentStep ? 'text-odc-600' : 'text-gray-500'}>
                        {index + 1}
                      </span>
                    )}
                  </button>
                  {index !== STEPS.length - 1 && (
                    <div className={`absolute top-4 w-full h-0.5 ${index < currentStep ? 'bg-odc-600' : 'bg-gray-300'}`} style={{ left: '2rem' }} />
                  )}
                </div>
                <div className="mt-2 hidden sm:block">
                  <span className={`text-xs font-medium ${index <= currentStep ? 'text-odc-600' : 'text-gray-500'}`}>
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
            onSelect={(type) => updateCurrentDoor({
              doorType: type,
              doorSeries: '',
              panelColor: '',
              panelDesign: '',
              // Reset windows to prevent stale state
              hasWindows: false,
              windowInsert: null,
              windowPositions: [],
              windowQty: 0,
              glassPaneType: null,
              glassColor: null,
              trackMount: 'bracket',
              // Set track defaults based on door type
              trackRadius: type === 'commercial' ? '15' : '12',
              trackThickness: type === 'commercial' ? '3' : '2',
            })}
          />
        )}

        {/* Step 2: Door Series */}
        {STEPS[currentStep].id === 'series' && config && (
          <DoorSeriesStep
            series={config.doorSeries[currentDoor.doorType] || []}
            selected={currentDoor.doorSeries}
            onSelect={(series) => {
              const isCommercialSeries = ['TX380', 'TX450', 'TX500', 'TX450-20', 'TX500-20'].includes(series)
              const isAluminumSeries = ['AL976', 'PANORAMA', 'SOLALITE'].includes(series)
              updateCurrentDoor({
                doorSeries: series,
                panelColor: isAluminumSeries ? 'CLEAR_ANODIZED' : '',
                panelDesign: isCommercialSeries ? 'UDC' : isAluminumSeries ? 'FLUSH' : '',
                // Reset windows on series change (prevents stale state from previous config)
                hasWindows: false,
                windowInsert: null,
                windowPositions: [],
                windowQty: 0,
                glassPaneType: null,
                glassColor: null,
                ...(isCommercialSeries ? { trackThickness: '3' } : {}),
                ...(isAluminumSeries ? {
                  glassPaneType: series === 'AL976' ? 'INSULATED' : null,
                  glassColor: 'CLEAR',
                } : {}),
                // Craft series includes windows as standard
                ...(series === 'CRAFT' ? { hasWindows: true, windowInsert: '34X16_THERMOPANE', windowPositions: [] } : {})
              })
            }}
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
            config={config}
            onChange={(updates) => {
              // Craft series: auto-fill windows in top panel when design is selected
              if (currentDoor.doorSeries === 'CRAFT' && updates.panelDesign && updates.panelDesign !== 'FLUSH') {
                const widthFeet = currentDoor.doorWidth / 12
                let windowCount
                if (widthFeet <= 9) windowCount = 2
                else if (widthFeet <= 12) windowCount = 3
                else windowCount = 4
                const topPanelWindows = Array.from({ length: windowCount }, (_, col) => ({ section: 1, col }))
                updateCurrentDoor({
                  ...updates,
                  hasWindows: true,
                  windowInsert: '34X16_THERMOPANE',
                  windowPositions: topPanelWindows,
                  glassPaneType: 'INSULATED',
                  glassColor: 'CLEAR',
                })
              } else if (currentDoor.doorSeries === 'CRAFT' && updates.panelDesign === 'FLUSH') {
                updateCurrentDoor({
                  ...updates,
                  hasWindows: false,
                  windowInsert: null,
                  windowPositions: [],
                })
              } else {
                updateCurrentDoor(updates)
              }
            }}
          />
        )}

        {/* Step 5: Windows (skip for aluminum — all panels are full-view) */}
        {STEPS[currentStep].id === 'windows' && config && (
          currentDoor.doorType === 'aluminium' ? (
            <div className="p-4 bg-odc-50 rounded-md">
              <p className="text-sm text-odc-700">
                All panels on this aluminum door are full-view {
                  ['PANORAMA', 'SOLALITE'].includes(currentDoor.doorSeries) ? 'polycarbonate' : 'glass'
                } sections. Window options were configured in the Design step.
              </p>
            </div>
          ) : (
            <WindowsStep
              door={currentDoor}
              windowInserts={config.windowInserts}
              commercialWindowTypes={config.commercialWindowTypes}
              glazingOptions={config.glazingOptions}
              config={config}
              onChange={updateCurrentDoor}
            />
          )
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
            quoteName={quoteName}
            quoteDescription={quoteDescription}
            poNumber={poNumber}
            deliveryType={deliveryType}
            onNameChange={setQuoteName}
            onDescriptionChange={setQuoteDescription}
            onPoNumberChange={setPoNumber}
            onDeliveryTypeChange={setDeliveryType}
            onSave={handleSave}
            isSaving={saving}
            errors={errors}
            isBCLinked={isBCLinked}
            pricingData={pricingData}
            pricingLoading={pricingLoading}
            onGetPricing={handleGetPricing}
            onConfirmSubmit={handleConfirmSubmit}
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
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50 disabled:cursor-not-allowed"
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
              ? 'border-odc-500 bg-blue-50'
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
              ? 'border-odc-500 bg-blue-50'
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
                  ? 'border-odc-500 bg-blue-50 text-odc-700'
                  : 'border-gray-300 hover:border-gray-400'
              }`}
            >
              {size.label}
            </button>
          ))}
        </div>
      </div>

      {/* Custom Dimensions — Feet + Inches */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Width</label>
          <div className="flex gap-2">
            <div className="flex-1">
              <input
                type="number"
                value={Math.floor(door.doorWidth / 12)}
                onChange={(e) => {
                  const feet = parseInt(e.target.value) || 0
                  const inches = door.doorWidth % 12
                  onChange({ doorWidth: feet * 12 + inches })
                }}
                min={Math.floor((specs.minWidth || 60) / 12)}
                max={Math.ceil((specs.maxWidth || 288) / 12)}
                className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-odc-500 focus:border-odc-500"
              />
              <p className="mt-1 text-xs text-gray-500">feet</p>
            </div>
            <div className="w-20">
              <input
                type="number"
                value={door.doorWidth % 12}
                onChange={(e) => {
                  const feet = Math.floor(door.doorWidth / 12)
                  const inches = Math.max(0, Math.min(11, parseInt(e.target.value) || 0))
                  onChange({ doorWidth: feet * 12 + inches })
                }}
                min={0}
                max={11}
                className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-odc-500 focus:border-odc-500"
              />
              <p className="mt-1 text-xs text-gray-500">inches</p>
            </div>
          </div>
          <p className="mt-1 text-xs text-gray-400">{door.doorWidth}" total</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Height</label>
          <div className="flex gap-2">
            <div className="flex-1">
              <input
                type="number"
                value={Math.floor(door.doorHeight / 12)}
                onChange={(e) => {
                  const feet = parseInt(e.target.value) || 0
                  const inches = door.doorHeight % 12
                  onChange({ doorHeight: feet * 12 + inches })
                }}
                min={Math.floor((specs.minHeight || 72) / 12)}
                max={Math.ceil((specs.maxHeight || 384) / 12)}
                className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-odc-500 focus:border-odc-500"
              />
              <p className="mt-1 text-xs text-gray-500">feet</p>
            </div>
            <div className="w-20">
              <input
                type="number"
                value={door.doorHeight % 12}
                onChange={(e) => {
                  const feet = Math.floor(door.doorHeight / 12)
                  const inches = Math.max(0, Math.min(11, parseInt(e.target.value) || 0))
                  onChange({ doorHeight: feet * 12 + inches })
                }}
                min={0}
                max={11}
                className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-odc-500 focus:border-odc-500"
              />
              <p className="mt-1 text-xs text-gray-500">inches</p>
            </div>
          </div>
          <p className="mt-1 text-xs text-gray-400">{door.doorHeight}" total</p>
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
            className="w-full border border-gray-300 rounded-md shadow-sm px-3 py-2 focus:ring-odc-500 focus:border-odc-500"
          />
        </div>
      </div>

      {/* Constraints Info */}
      {specs.maxWidth && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
          <p className="text-sm text-odc-700">
            <strong>{series?.name}:</strong> Max width {specs.maxWidth}" ({Math.floor(specs.maxWidth / 12)}')
            {specs.sectionHeights && `, Section heights: ${specs.sectionHeights.join('", ')}`}
          </p>
        </div>
      )}
    </div>
  )
}

function DesignStep({ door, colors, panelDesigns, config, onChange }) {
  const isAluminium = door.doorType === 'aluminium'
  const seriesData = config?.doorSeries?.aluminium?.find(s => s.id === door.doorSeries)

  // Get colors for current series
  const colorMap = {
    'KANATA': 'KANATA',
    'CRAFT': 'CRAFT',
    'TX380': 'COMMERCIAL',
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
    'TX380': 'COMMERCIAL',
    'TX450': 'COMMERCIAL',
    'TX500': 'COMMERCIAL',
    'TX450-20': 'COMMERCIAL_20',
    'TX500-20': 'COMMERCIAL_20',
  }
  const designKey = designMap[door.doorSeries] || 'KANATA'
  const availableDesigns = panelDesigns?.[designKey] || []

  // Auto-select panel design if there's only one option and none selected
  useEffect(() => {
    if (!isAluminium && availableDesigns.length === 1 && !door.panelDesign) {
      const design = availableDesigns[0]
      onChange({ panelDesign: design.code || design.id })
    }
  }, [availableDesigns, door.panelDesign, onChange, isAluminium])

  // Aluminum doors: show finishes + glazing options instead of colors/designs
  if (isAluminium) {
    const finishes = seriesData?.finishes || [{ id: 'CLEAR_ANODIZED', name: 'Clear Anodized' }]
    const customFinishNote = seriesData?.customFinishNote
    const glazingType = seriesData?.glazingType || 'glass'
    const isGlass = glazingType === 'glass'
    const glazingOptions = seriesData?.glazingOptions || (isGlass
      ? [{ id: 'CLEAR', name: 'Clear' }, { id: 'ETCHED', name: 'Etched' }, { id: 'SUPER_GREY', name: 'Super Grey' }]
      : [{ id: 'CLEAR', name: 'Clear' }, { id: 'LIGHT_BRONZE', name: 'Light Bronze' }]
    )
    const paneTypes = seriesData?.paneTypes || []
    const seriesName = seriesData?.name || door.doorSeries

    return (
      <div className="space-y-6">
        <div className="p-3 bg-odc-50 rounded-md">
          <p className="text-sm text-odc-700">
            <strong>{seriesName} Full View Door</strong> — all panels are full aluminum/{isGlass ? 'glass' : 'polycarbonate'} sections.
          </p>
        </div>

        {/* Finish */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Finish</label>
          <div className="flex flex-wrap gap-3">
            {finishes.map(f => (
              <button
                key={f.id}
                onClick={() => onChange({ panelColor: f.id })}
                className={`px-4 py-2 text-sm rounded-md border ${
                  (door.panelColor || finishes[0]?.id) === f.id
                    ? 'border-odc-500 bg-odc-100 text-odc-700'
                    : 'border-gray-300 hover:border-gray-400'
                }`}
              >
                {f.name}
              </button>
            ))}
          </div>
          {customFinishNote && (
            <p className="mt-1 text-xs text-gray-500 italic">{customFinishNote}</p>
          )}
        </div>

        {/* Glass Type — only for glass series (AL976) */}
        {isGlass && paneTypes.length > 0 && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Glass Type</label>
            <div className="flex space-x-3">
              {paneTypes.map(pt => (
                <button
                  key={pt.id}
                  onClick={() => onChange({ glassPaneType: pt.id })}
                  className={`px-4 py-2 text-sm rounded-md border ${
                    (door.glassPaneType || 'INSULATED') === pt.id
                      ? 'border-odc-500 bg-odc-100 text-odc-700'
                      : 'border-gray-300 hover:border-gray-400'
                  }`}
                >
                  {pt.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Glazing Color */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {isGlass ? 'Glass Color' : 'Polycarbonate Color'}
          </label>
          <div className="flex space-x-3">
            {glazingOptions.map(gc => (
              <button
                key={gc.id}
                onClick={() => onChange({ glassColor: gc.id })}
                className={`px-4 py-2 text-sm rounded-md border ${
                  (door.glassColor || 'CLEAR') === gc.id
                    ? 'border-odc-500 bg-odc-100 text-odc-700'
                    : 'border-gray-300 hover:border-gray-400'
                }`}
              >
                {gc.name}
              </button>
            ))}
          </div>
        </div>
      </div>
    )
  }

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
                  ? 'border-odc-500 ring-2 ring-blue-200'
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
                  ? 'border-odc-500 bg-blue-50'
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

function WindowsStep({ door, windowInserts, commercialWindowTypes, glazingOptions, config, onChange }) {
  const [hoveredStamp, setHoveredStamp] = useState(null)
  const hasWindows = door.hasWindows || false
  const isCommercial = door.doorType === 'commercial'

  // Calculate panel count based on height (matching DoorPreview.jsx sectionConfig)
  const getPanelCount = (heightInches, series) => {
    if (series === 'CRAFT') return 3  // Craft series: always 3 panels
    if (heightInches <= 96) return 4   // 7' and 8' doors = 4 panels
    if (heightInches <= 120) return 5  // 9' and 10' doors = 5 panels
    if (heightInches <= 144) return 6  // 11' and 12' doors = 6 panels
    if (heightInches <= 168) return 7  // 13' and 14' doors = 7 panels
    return 8
  }
  const panelCount = getPanelCount(door.doorHeight, door.doorSeries)

  // Calculate stamp columns based on door width and panel design (same logic as DoorPreview)
  const isCraft = door.doorSeries === 'CRAFT'
  const getStampColumns = (widthInches, panelDesign) => {
    const widthFeet = widthInches / 12
    let longCols
    if (widthFeet <= 9) longCols = 2
    else if (widthFeet <= 12) longCols = 3
    else if (widthFeet <= 16) longCols = 4
    else if (widthFeet <= 19) longCols = 5
    else longCols = 6
    // Craft series: all stamps use same count (no doubling for short stamps)
    if (isCraft) return longCols
    if (['SH', 'BC'].includes(panelDesign)) return longCols * 2
    return longCols
  }
  const stampColumns = getStampColumns(door.doorWidth, door.panelDesign)

  // Long windows on SH/BC span 2 stamp columns each — grid shows half as many cells
  const isLongOnStandard = (door.windowSize || 'long') === 'long' && ['SH', 'BC'].includes(door.panelDesign)
  const gridColumns = isLongOnStandard ? Math.floor(stampColumns / 2) : stampColumns

  // Get window positions, defaulting to empty array
  const windowPositions = door.windowPositions || []

  // Check if a position has a window (positions stored as even col indices in long mode)
  const hasWindowAt = (section, col) => {
    return windowPositions.some(pos => pos.section === section && pos.col === col)
  }

  // Toggle window at a stamp position
  const toggleWindow = (section, col) => {
    // Craft series: windows only in top panel (section 1)
    if (door.doorSeries === 'CRAFT' && section !== 1) return

    // Long windows on SH/BC: normalize to even column (anchor of the 2-stamp pair)
    const normalizedCol = isLongOnStandard ? Math.floor(col / 2) * 2 : col

    const existing = windowPositions.find(pos => pos.section === section && pos.col === normalizedCol)
    let newPositions
    if (existing) {
      newPositions = windowPositions.filter(pos => !(pos.section === section && pos.col === normalizedCol))
    } else {
      newPositions = [...windowPositions, { section, col: normalizedCol }]
    }
    onChange({ windowPositions: newPositions })
  }

  // Quick actions for common patterns
  const setTopRowWindows = () => {
    const positions = []
    const step = isLongOnStandard ? 2 : 1
    for (let col = 0; col < stampColumns; col += step) {
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
    const lastCol = isLongOnStandard ? stampColumns - 2 : stampColumns - 1
    for (let section = 1; section <= panelCount; section++) {
      positions.push({ section, col: lastCol })
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

  // Commercial window types (sizes) — no decorative inserts on commercial
  const commercialWindows = commercialWindowTypes

  // Commercial-specific helpers — matches COMMERCIAL WINDOW SPACING CALCULATOR spreadsheet
  // Panel width = full door width, Spaces = Qty + 1, Spacing = (PanelWidth - TotalWindowWidth) / Spaces
  const isV130G = door.windowInsert === 'V130G'

  const calculateRecommendedWindows = () => {
    if (!isCommercial || !door.windowInsert || door.windowInsert === 'NONE' || isV130G) return 0
    const windowSize = config?.commercialWindowSizes?.[door.windowInsert]
    if (!windowSize) return 0
    const windowWidth = windowSize.width
    const panelWidth = door.doorWidth  // Full door width per spreadsheet
    const optimalSpacing = 10
    const recommended = Math.floor((panelWidth - optimalSpacing) / (windowWidth + optimalSpacing))
    return Math.max(1, recommended)
  }

  const calculateSpacing = () => {
    if (!isCommercial || !door.windowInsert || door.windowInsert === 'NONE' || !door.windowQty || isV130G) return null
    const windowSize = config?.commercialWindowSizes?.[door.windowInsert]
    if (!windowSize) return null
    const windowWidth = windowSize.width
    const panelWidth = door.doorWidth  // Full door width per spreadsheet
    const totalWindowWidth = windowWidth * door.windowQty
    const spaces = door.windowQty + 1
    if (totalWindowWidth >= panelWidth) return null
    return ((panelWidth - totalWindowWidth) / spaces).toFixed(1)
  }

  const recommendedQty = calculateRecommendedWindows()
  const spacing = calculateSpacing()

  const handleCommercialWindowChange = (windowType) => {
    if (windowType === 'V130G') {
      // V130G replaces entire section — no quantity needed
      onChange({ windowInsert: windowType, windowQty: 1, windowSection: 1 })
      return
    }
    const windowSize = config?.commercialWindowSizes?.[windowType]
    if (windowSize) {
      const windowWidth = windowSize.width
      const panelWidth = door.doorWidth  // Full door width per spreadsheet
      const optimalSpacing = 10
      const qty = Math.max(1, Math.floor((panelWidth - optimalSpacing) / (windowWidth + optimalSpacing)))
      onChange({ windowInsert: windowType, windowQty: qty })
    } else {
      onChange({ windowInsert: windowType })
    }
  }

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
            windowPositions: [],
            glassPaneType: e.target.checked ? 'INSULATED' : null,
            glassColor: e.target.checked ? 'CLEAR' : null,
            windowInsert: 'NONE',
            hasInserts: false,
            ...(isCommercial && e.target.checked ? { windowFrameColor: 'BLACK' } : {}),
          })}
          className="h-4 w-4 text-odc-600 focus:ring-odc-500 border-gray-300 rounded"
        />
        <label htmlFor="hasWindows" className="text-sm font-medium text-gray-700">
          Include windows in this door
        </label>
      </div>

      {hasWindows && !isCommercial && isCraft && (
        <>
          {/* Craft series: windows auto-placed in top section, only glass color is configurable */}
          <div className="p-3 bg-blue-50 rounded-md">
            <p className="text-sm text-odc-700">
              Windows are automatically placed in the top section for Craft series doors.
            </p>
          </div>

          {/* Glass Color */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Glass Color
            </label>
            <div className="grid grid-cols-3 gap-3">
              {glassColorOptions.map((option) => (
                <button
                  key={option.id}
                  onClick={() => onChange({ glassColor: option.id })}
                  className={`p-3 rounded-lg border-2 flex flex-col items-center transition-all ${
                    door.glassColor === option.id
                      ? 'border-odc-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-400'
                  }`}
                >
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
        </>
      )}

      {hasWindows && !isCommercial && !isCraft && (
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
                  windowSize={door.windowSize || 'long'}
                  hasInserts={door.hasInserts || false}
                  glassColor={door.glassColor || 'CLEAR'}
                  windowFrameColor={door.windowFrameColor || 'MATCH'}
                  doorType={door.doorType || 'residential'}
                  doorSeries={door.doorSeries || ''}
                  windowQty={door.windowQty || 0}
                  windowSection={door.windowSection || 1}
                  showDimensions={false}
                  scale={0.7}
                  interactive={!isCommercial}
                  onStampClick={isCommercial ? undefined : toggleWindow}
                  highlightStamp={isCommercial ? null : hoveredStamp}
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
                      className="px-3 py-2 text-xs rounded-md border border-gray-300 hover:border-blue-400 hover:bg-blue-50"
                    >
                      Top Row
                    </button>
                    <button
                      onClick={setLeftColumnWindows}
                      className="px-3 py-2 text-xs rounded-md border border-gray-300 hover:border-blue-400 hover:bg-blue-50"
                    >
                      Left Column
                    </button>
                    <button
                      onClick={setRightColumnWindows}
                      className="px-3 py-2 text-xs rounded-md border border-gray-300 hover:border-blue-400 hover:bg-blue-50"
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
                    <strong>Door Grid:</strong> {panelCount} sections × {gridColumns} window positions
                    {isLongOnStandard && <span className="text-xs text-gray-500 ml-1">(each spans 2 stamps)</span>}
                  </p>
                  <p className="text-sm text-gray-600 mt-1">
                    <strong>Windows Selected:</strong> {windowPositions.length}
                  </p>
                </div>

                {/* Selected Windows List */}
                {windowPositions.length > 0 && (
                  <div className="p-3 bg-blue-50 rounded-md">
                    <p className="text-sm font-medium text-odc-700 mb-2">Window Positions:</p>
                    <div className="flex flex-wrap gap-1">
                      {windowPositions.map((pos, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center px-2 py-1 text-xs rounded bg-white border border-blue-200 text-odc-700"
                        >
                          S{pos.section}-C{pos.col + 1}
                          <button
                            onClick={() => toggleWindow(pos.section, pos.col)}
                            className="ml-1 text-blue-400 hover:text-red-500"
                          >
                            x
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
                        {[...Array(gridColumns)].map((_, gridCol) => {
                          const actualCol = isLongOnStandard ? gridCol * 2 : gridCol
                          const isActive = hasWindowAt(section + 1, actualCol)
                          const isHover = hoveredStamp?.section === section + 1 && hoveredStamp?.col === actualCol
                          return (
                            <button
                              key={gridCol}
                              onClick={() => toggleWindow(section + 1, actualCol)}
                              onMouseEnter={() => setHoveredStamp({ section: section + 1, col: actualCol })}
                              onMouseLeave={() => setHoveredStamp(null)}
                              className={`${isLongOnStandard ? 'w-14' : 'w-8'} h-8 rounded text-xs font-medium transition-all ${
                                isActive
                                  ? 'bg-sky-400 text-white border-2 border-sky-500'
                                  : isHover
                                    ? 'bg-blue-100 border-2 border-blue-300'
                                    : 'bg-gray-100 border border-gray-300 hover:bg-gray-200'
                              }`}
                              title={isLongOnStandard
                                ? `Section ${section + 1}, Stamps ${actualCol + 1}–${actualCol + 2}`
                                : `Section ${section + 1}, Column ${actualCol + 1}`}
                            >
                              {isActive ? '☐' : ''}
                            </button>
                          )
                        })}
                        <span className="text-xs text-gray-400 ml-1 self-center">S{section + 1}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Step 2: Window Size (SHORT vs LONG) */}
          {(() => {
            const isLongOnlyDesign = ['SHXL', 'BCXL'].includes(door.panelDesign)
            if (isLongOnlyDesign) {
              if (door.windowSize === 'short') onChange({ windowSize: 'long', hasInserts: false, windowPositions: [] })
              return null
            }
            return (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  2. Window Size
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => onChange({ windowSize: 'long', hasInserts: false, windowInsert: 'NONE', windowPositions: [] })}
                    className={`p-3 rounded-lg border-2 text-left transition-all ${
                      (door.windowSize || 'long') === 'long'
                        ? 'border-odc-500 bg-odc-50'
                        : 'border-gray-200 hover:border-gray-400'
                    }`}
                  >
                    <span className="block font-medium text-gray-900 text-sm">Long Window</span>
                    <span className="block text-xs text-gray-500 mt-1">Full stamp width — optional decorative inserts available</span>
                  </button>
                  <button
                    onClick={() => onChange({ windowSize: 'short', hasInserts: false, windowInsert: 'NONE', windowPositions: [] })}
                    className={`p-3 rounded-lg border-2 text-left transition-all ${
                      door.windowSize === 'short'
                        ? 'border-odc-500 bg-odc-50'
                        : 'border-gray-200 hover:border-gray-400'
                    }`}
                  >
                    <span className="block font-medium text-gray-900 text-sm">Short Window</span>
                    <span className="block text-xs text-gray-500 mt-1">Half stamp width — fits one short stamp</span>
                  </button>
                </div>
              </div>
            )
          })()}

          {/* Step 3: Glass Pane Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              3. Glass Pane Type
            </label>
            <div className="grid grid-cols-2 gap-3">
              {glassPaneOptions.map((option) => (
                <button
                  key={option.id}
                  onClick={() => onChange({ glassPaneType: option.id })}
                  className={`p-4 rounded-lg border-2 text-left transition-all ${
                    door.glassPaneType === option.id
                      ? 'border-odc-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-400'
                  }`}
                >
                  <span className="block font-medium text-gray-900">{option.name}</span>
                  <span className="block text-xs text-gray-500 mt-1">{option.description}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Step 4: Glass Color */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              4. Glass Color
            </label>
            <div className="grid grid-cols-3 gap-3">
              {glassColorOptions.map((option) => (
                <button
                  key={option.id}
                  onClick={() => onChange({ glassColor: option.id })}
                  className={`p-3 rounded-lg border-2 flex flex-col items-center transition-all ${
                    door.glassColor === option.id
                      ? 'border-odc-500 bg-blue-50'
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

          {/* Step 5: Window Frame Color */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              5. Window Frame Color
            </label>
            <select
              value={door.windowFrameColor || 'MATCH'}
              onChange={(e) => onChange({ windowFrameColor: e.target.value })}
              className="w-full max-w-xs rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-odc-500 focus:ring-1 focus:ring-odc-500"
            >
              <option value="MATCH">Match Door Color (Standard)</option>
              {config?.colors && Object.values(config.colors).flat()
                .filter((c, i, arr) => arr.findIndex(x => x.id === c.id) === i)
                .filter(c => c.id !== door.panelColor && c.id !== 'CUSTOM')
                .map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))
              }
            </select>
          </div>

          {/* Step 6: Optional Window Inserts (LONG windows only) */}
          {door.windowSize !== 'short' && (
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
                className="h-4 w-4 text-odc-600 focus:ring-odc-500 border-gray-300 rounded"
              />
              <label htmlFor="hasInserts" className="text-sm font-medium text-gray-700">
                Add decorative window inserts (optional upgrade)
              </label>
            </div>

            {door.hasInserts && windowInserts && (
              <div className="pl-7">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  6. Select Insert Style
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
                                ? 'border-odc-500 bg-blue-50'
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
          )}
        </>
      )}

      {/* Commercial window flow */}
      {hasWindows && isCommercial && (
        <>
          {/* Door Preview */}
          <div className="flex-shrink-0">
            <DoorPreview
              width={door.doorWidth}
              height={door.doorHeight}
              color={door.panelColor || 'WHITE'}
              panelDesign={door.panelDesign || 'FLUSH'}
              windowInsert={door.windowInsert}
              windowPositions={[]}
              hasInserts={false}
              glassColor={door.glassColor || 'CLEAR'}
              windowFrameColor={door.windowFrameColor || 'BLACK'}
              doorType={door.doorType || 'commercial'}
              doorSeries={door.doorSeries || ''}
              windowQty={door.windowQty || 0}
              windowSection={door.windowSection || 1}
              showDimensions={true}
              scale={0.6}
            />
          </div>

          {/* Window Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Window Type
            </label>
            <div className="space-y-4">
              {commercialWindows && Object.entries(commercialWindows).map(([style, inserts]) => (
                <div key={style}>
                  <h4 className="text-sm font-medium text-gray-600 mb-2">{style}</h4>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    {inserts.map((insert) => (
                      <button
                        key={insert.id}
                        onClick={() => handleCommercialWindowChange(insert.id)}
                        className={`px-3 py-2 text-sm rounded-md border text-left ${
                          door.windowInsert === insert.id
                            ? 'border-odc-500 bg-blue-50 text-odc-700'
                            : 'border-gray-300 hover:border-gray-400'
                        }`}
                      >
                        <span className="font-medium">{insert.name}</span>
                        {insert.sectionType && (
                          <span className="block text-xs text-gray-400">{insert.sectionType}</span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* V130G: full view section info */}
          {isV130G && (
            <div className="bg-blue-50 rounded-lg p-4">
              <p className="text-sm text-odc-700">
                <strong>V130G Full View</strong> — replaces an insulated section with a full aluminum/glass panel (AL976 material).
              </p>
              <div className="mt-3">
                <label className="block text-sm font-medium text-gray-700 mb-1">Glass Type</label>
                <div className="flex space-x-3">
                  {['thermal', 'single'].map(gt => (
                    <button
                      key={gt}
                      onClick={() => onChange({ glassPaneType: gt === 'thermal' ? 'INSULATED' : 'SINGLE' })}
                      className={`px-4 py-2 text-sm rounded-md border ${
                        (gt === 'thermal' && door.glassPaneType === 'INSULATED') || (gt === 'single' && door.glassPaneType === 'SINGLE')
                          ? 'border-odc-500 bg-blue-100 text-odc-700'
                          : 'border-gray-300 hover:border-gray-400'
                      }`}
                    >
                      {gt === 'thermal' ? 'Thermal Glass' : 'Single Glass'}
                    </button>
                  ))}
                </div>
              </div>
              <div className="mt-3">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Number of V130G sections
                </label>
                <div className="flex items-center space-x-4">
                  <button
                    onClick={() => onChange({ windowQty: Math.max(1, (door.windowQty || 1) - 1) })}
                    className="w-10 h-10 rounded-md border border-gray-300 bg-white hover:bg-gray-50 text-xl font-bold"
                  >-</button>
                  <span className="text-lg font-medium w-10 text-center">{door.windowQty || 1}</span>
                  <button
                    onClick={() => onChange({ windowQty: Math.min(panelCount, (door.windowQty || 1) + 1) })}
                    className="w-10 h-10 rounded-md border border-gray-300 bg-white hover:bg-gray-50 text-xl font-bold"
                  >+</button>
                </div>
              </div>
            </div>
          )}

          {/* Commercial Window Quantity (non-V130G) */}
          {!isV130G && (
            <div className="bg-blue-50 rounded-lg p-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Window Quantity
              </label>
              <div className="flex items-center space-x-4">
                <button
                  onClick={() => onChange({ windowQty: Math.max(0, (door.windowQty || 0) - 1) })}
                  className="w-10 h-10 rounded-md border border-gray-300 bg-white hover:bg-gray-50 text-xl font-bold"
                >
                  -
                </button>
                <input
                  type="number"
                  value={door.windowQty || 0}
                  onChange={(e) => onChange({ windowQty: Math.max(0, parseInt(e.target.value) || 0) })}
                  className="w-20 text-center border border-gray-300 rounded-md shadow-sm px-3 py-2"
                  min={0}
                />
                <button
                  onClick={() => onChange({ windowQty: (door.windowQty || 0) + 1 })}
                  className="w-10 h-10 rounded-md border border-gray-300 bg-white hover:bg-gray-50 text-xl font-bold"
                >
                  +
                </button>
                <button
                  onClick={() => onChange({ windowQty: recommendedQty })}
                  className="px-3 py-2 text-sm bg-odc-600 text-white rounded-md hover:bg-odc-700"
                >
                  Use Recommended ({recommendedQty})
                </button>
              </div>
              {spacing && (
                <p className="mt-2 text-sm text-odc-700">
                  Spacing between windows: <strong>{spacing}"</strong>
                </p>
              )}
              {door.windowQty > 0 && !spacing && (
                <p className="mt-2 text-sm text-red-600">
                  Too many windows for this door width. Please reduce quantity.
                </p>
              )}
            </div>
          )}

          {/* Commercial Window Section Selection */}
          {door.windowQty > 0 && (
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
                        ? 'border-odc-500 bg-blue-50 text-odc-700'
                        : 'border-gray-300 hover:border-gray-400'
                    }`}
                  >
                    {i + 1}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-xs text-gray-500">
                This door has {panelCount} panels. Select which panel to place the {door.windowQty} window{door.windowQty > 1 ? 's' : ''} in.
              </p>
            </div>
          )}

          {/* Commercial Frame Color */}
          {config?.commercialWindowFrameColors && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Frame Color
              </label>
              <p className="text-xs text-gray-500 mb-2">Standard is black. Inside frame is always white.</p>
              <div className="grid grid-cols-2 gap-3">
                {config.commercialWindowFrameColors.map((color) => (
                  <button
                    key={color.id}
                    onClick={() => onChange({ windowFrameColor: color.id })}
                    className={`p-3 rounded-lg border-2 flex items-center space-x-3 ${
                      (door.windowFrameColor || 'BLACK') === color.id
                        ? 'border-odc-500 bg-blue-50'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <div
                      className="w-8 h-8 rounded-full border border-gray-300"
                      style={{ backgroundColor: color.hex }}
                    />
                    <div className="text-left">
                      <span className="text-sm font-medium text-gray-900">{color.name}{color.default && ' (Standard)'}</span>
                      <span className="block text-xs text-gray-500">{color.description}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

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
                      ? 'border-odc-500 bg-blue-50 text-odc-700'
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

  // Spring cycle options
  // Spring cycle options (must match MIP capacity data in spring calculator)
  const springCycleOptions = [
    { id: 10000, name: '10,000 cycles' },
    { id: 15000, name: '15,000 cycles' },
    { id: 25000, name: '25,000 cycles' },
    { id: 50000, name: '50,000 cycles' },
    { id: 100000, name: '100,000 cycles' },
  ]

  // Shaft type options - auto-detect based on width (14'2" = 170")
  const shaftTypeOptions = [
    { id: 'auto', name: 'Auto (Recommended)', description: door.doorWidth <= 170 ? 'Single shaft (\u226414\'2")' : 'Split shaft with coupler (>14\'2")' },
    { id: 'single', name: 'Single Shaft', description: 'No coupler - up to 14\'2" wide' },
    { id: 'split', name: 'Split Shaft', description: 'Two pieces with coupler' },
  ]

  // Warn if single shaft selected for wide door
  const shaftWarning = door.shaftType === 'single' && door.doorWidth > 170

  // Craft series: only 2" track and no 12" radius option
  const isCraftDoor = door.doorSeries === 'CRAFT'
  const filteredRadius = isCraftDoor
    ? trackOptions?.radius?.filter(r => r.id !== '12')
    : trackOptions?.radius
  const filteredThickness = isCraftDoor
    ? trackOptions?.thickness?.filter(t => t.id !== '3')
    : trackOptions?.thickness

  // Determine allowed track thickness based on selected radius
  const selectedRadius = filteredRadius?.find(r => r.id === door.trackRadius)
  const allowedThickness = selectedRadius?.allowedThickness?.filter(t => !isCraftDoor || t !== '3') || ['2']
  const isLowHeadroom = door.liftType === 'low_headroom'

  // Handle radius change - auto-correct track thickness if needed
  const handleRadiusChange = (radiusId) => {
    const radius = trackOptions?.radius?.find(r => r.id === radiusId)
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
    const liftOption = trackOptions?.liftType?.find(lt => lt.id === liftTypeId)
    const updates = { liftType: liftTypeId }
    // Low headroom forces 2" track
    if (liftOption?.forcedTrackSize) {
      updates.trackThickness = String(liftOption.forcedTrackSize)
    }
    // Clear high lift inches when switching away from high_lift
    if (liftTypeId !== 'high_lift') {
      updates.highLiftInches = null
    }
    onChange(updates)
  }

  return (
    <div className="space-y-6">
      {/* Lift Type */}
      {trackOptions?.liftType && (
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
                    ? 'border-odc-500 bg-blue-50'
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

      {/* High Lift Inches - only shown for high_lift */}
      {door.liftType === 'high_lift' && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            High Lift (inches)
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={1}
              value={door.highLiftInches || ''}
              onChange={(e) => onChange({ highLiftInches: parseInt(e.target.value) || null })}
              className="w-24 rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 text-sm"
              placeholder="inches"
            />
            <span className="text-sm text-gray-500">inches above door opening</span>
          </div>
          {door.highLiftInches > 0 && (
            <div className="mt-2 text-sm text-amber-700">
              Total effective height: {door.doorHeight + door.highLiftInches}"
            </div>
          )}
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
              {filteredRadius?.map((option) => (
                <label key={option.id} className="flex items-center">
                  <input
                    type="radio"
                    name="trackRadius"
                    value={option.id}
                    checked={door.trackRadius === option.id}
                    onChange={(e) => handleRadiusChange(e.target.value)}
                    className="h-4 w-4 text-odc-600 focus:ring-odc-500 border-gray-300"
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
              {filteredThickness?.map((option) => {
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
                      className="h-4 w-4 text-odc-600 focus:ring-odc-500 border-gray-300"
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

      {/* Track Mount Type */}
      {door.liftType === 'standard' && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Track Mount
          </label>
          <div className="grid grid-cols-2 gap-3 max-w-md">
            {[
              { id: 'bracket', name: 'Bracket Mount', description: 'Standard bracket mounting' },
              { id: 'angle', name: 'Angle Mount', description: 'Angle iron mounting' },
            ].map((option) => (
              <button
                key={option.id}
                onClick={() => onChange({ trackMount: option.id })}
                className={`p-3 rounded-lg border-2 text-center transition-all ${
                  (door.trackMount || 'bracket') === option.id
                    ? 'border-odc-500 bg-odc-50'
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
        <select
          value={door.targetCycles || 10000}
          onChange={(e) => onChange({ targetCycles: Number(e.target.value) })}
          className="w-full md:w-64 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-odc-500 focus:border-odc-500"
        >
          {springCycleOptions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
      </div>

      {/* Shaft Type - all door types */}
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
                  ? 'border-odc-500 bg-odc-50'
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

        {/* Preset buttons */}
        <div className="flex gap-2 mb-3">
          <button
            onClick={() => onChange({
              hardware: { panels: true, tracks: true, springs: true, struts: true, hardwareKits: true, weatherStripping: true, bottomRetainer: true, shafts: true }
            })}
            className={`px-3 py-1.5 text-xs font-medium rounded-full border transition-all ${
              door.hardware.panels !== false && door.hardware.tracks !== false && door.hardware.springs !== false
                && door.hardware.hardwareKits !== false && door.hardware.shafts !== false
                ? 'border-odc-500 bg-blue-50 text-odc-700'
                : 'border-gray-300 text-gray-600 hover:border-gray-400'
            }`}
          >
            Complete Door
          </button>
          <button
            onClick={() => onChange({
              hardware: { panels: true, tracks: false, springs: false, struts: false, hardwareKits: false, weatherStripping: false, bottomRetainer: true, shafts: false }
            })}
            className={`px-3 py-1.5 text-xs font-medium rounded-full border transition-all ${
              door.hardware.panels !== false && door.hardware.tracks === false && door.hardware.springs === false
                ? 'border-odc-500 bg-blue-50 text-odc-700'
                : 'border-gray-300 text-gray-600 hover:border-gray-400'
            }`}
          >
            Door Face Only
          </button>
          <button
            onClick={() => onChange({
              hardware: { panels: false, tracks: true, springs: true, struts: true, hardwareKits: true, weatherStripping: true, bottomRetainer: true, shafts: true }
            })}
            className={`px-3 py-1.5 text-xs font-medium rounded-full border transition-all ${
              door.hardware.panels === false && door.hardware.tracks !== false && door.hardware.springs !== false
                ? 'border-odc-500 bg-blue-50 text-odc-700'
                : 'border-gray-300 text-gray-600 hover:border-gray-400'
            }`}
          >
            Hardware Only
          </button>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {hardwareOptions?.map((option) => (
            <label key={option.id} className="flex items-start p-3 border rounded-lg cursor-pointer hover:bg-gray-50">
              <input
                type="checkbox"
                checked={door.hardware[option.id] !== false}
                onChange={(e) => onChange({
                  hardware: { ...door.hardware, [option.id]: e.target.checked }
                })}
                className="h-4 w-4 mt-0.5 text-odc-600 focus:ring-odc-500 border-gray-300 rounded"
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
                ? 'border-odc-500 bg-blue-50'
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
                  ? 'border-odc-500 bg-blue-50'
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

function ReviewStep({ doors, config, quoteName, quoteDescription, poNumber, deliveryType, onNameChange, onDescriptionChange, onPoNumberChange, onDeliveryTypeChange, onSave, isSaving, errors, isBCLinked, pricingData, pricingLoading, onGetPricing, onConfirmSubmit }) {
  function getSeriesName(doorType, seriesId) {
    const series = config?.doorSeries?.[doorType]?.find(s => s.id === seriesId)
    return series?.name || seriesId
  }

  function getColorName(seriesId, colorId) {
    const colorMap = {
      'KANATA': 'KANATA',
      'CRAFT': 'CRAFT',
      'TX380': 'COMMERCIAL',
      'TX450': 'COMMERCIAL',
      'TX500': 'COMMERCIAL',
      'TX450-20': 'COMMERCIAL',
      'TX500-20': 'COMMERCIAL',
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
              } focus:border-odc-500 focus:ring-odc-500`}
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
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
              placeholder="Any additional notes..."
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              PO / Reference Number (optional)
            </label>
            <input
              type="text"
              value={poNumber || ''}
              onChange={(e) => onPoNumberChange(e.target.value)}
              className="mt-1 block w-full md:w-64 rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
              placeholder="e.g., PO-12345"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Delivery Method *
            </label>
            <div className="flex space-x-6">
              <label className={`flex items-center space-x-2 cursor-pointer px-4 py-2 rounded-md border-2 transition-all ${
                deliveryType === 'delivery' ? 'border-odc-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
              }`}>
                <input
                  type="radio"
                  name="deliveryType"
                  value="delivery"
                  checked={deliveryType === 'delivery'}
                  onChange={(e) => onDeliveryTypeChange(e.target.value)}
                  className="text-odc-600 focus:ring-odc-500"
                />
                <div>
                  <span className="text-sm font-medium text-gray-900">Delivery</span>
                  <p className="text-xs text-gray-500">Freight charges apply</p>
                </div>
              </label>
              <label className={`flex items-center space-x-2 cursor-pointer px-4 py-2 rounded-md border-2 transition-all ${
                deliveryType === 'pickup' ? 'border-odc-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
              }`}>
                <input
                  type="radio"
                  name="deliveryType"
                  value="pickup"
                  checked={deliveryType === 'pickup'}
                  onChange={(e) => onDeliveryTypeChange(e.target.value)}
                  className="text-odc-600 focus:ring-odc-500"
                />
                <div>
                  <span className="text-sm font-medium text-gray-900">Pickup</span>
                  <p className="text-xs text-gray-500">No freight charges</p>
                </div>
              </label>
            </div>
            {errors.delivery && <p className="mt-1 text-sm text-red-600">{errors.delivery}</p>}
          </div>
        </div>
      </div>

      {/* Configuration Summary */}
      <div className="bg-gray-50 rounded-lg p-4">
        <h3 className="font-medium text-gray-900 mb-4">Configuration Summary</h3>

        {doors.map((door, index) => (
          <div key={index} className="mb-6 last:mb-0">
            <h4 className="text-sm font-medium text-odc-600 mb-2">
              Door {index + 1} {door.doorCount > 1 && `(Qty: ${door.doorCount})`}
            </h4>

            {/* Door Preview + Details */}
            <div className="flex flex-col md:flex-row gap-6">
              {/* SVG Preview */}
              <div className="flex-shrink-0">
                <DoorPreview
                  width={door.doorWidth}
                  height={door.doorHeight}
                  color={door.panelColor}
                  panelDesign={door.panelDesign}
                  windowInsert={door.windowInsert}
                  windowSection={door.windowSection}
                  windowPositions={door.windowPositions}
                  hasInserts={door.hasInserts || false}
                  glassColor={door.glassColor || 'CLEAR'}
                  windowQty={door.windowQty || 0}
                  windowFrameColor={door.windowFrameColor || 'MATCH'}
                  doorType={door.doorType}
                  doorSeries={door.doorSeries || ''}
                  showDimensions={true}
                  scale={0.6}
                />
              </div>

              {/* Details Grid */}
              <div className="flex-grow">
                <div className="grid grid-cols-2 gap-4 text-sm">
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
                      {Math.floor(door.doorWidth / 12)}'{door.doorWidth % 12}" x {Math.floor(door.doorHeight / 12)}'{door.doorHeight % 12}"
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
                      {door.hasWindows && door.windowPositions?.length > 0
                        ? `${door.windowPositions.length} window${door.windowPositions.length > 1 ? 's' : ''}`
                        : door.doorType === 'commercial' && door.windowInsert !== 'NONE'
                          ? `${door.windowQty || 0} windows (${door.windowFrameColor || 'BLACK'} frame)`
                          : 'No'}
                    </span>
                  </div>
                  {door.hasWindows && (
                    <>
                      <div>
                        <span className="text-gray-500">Glass:</span>
                        <span className="ml-2 text-gray-900">
                          {door.glassPaneType === 'INSULATED' ? 'Insulated' : door.glassPaneType === 'SINGLE' ? 'Single' : '-'}, {door.glassColor || 'Clear'}
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
                  {door.liftType === 'high_lift' && door.highLiftInches > 0 && (
                    <div>
                      <span className="text-gray-500">High Lift:</span>
                      <span className="ml-2 text-gray-900">
                        +{door.highLiftInches}" (effective height: {door.doorHeight + door.highLiftInches}")
                      </span>
                    </div>
                  )}
                  {door.liftType === 'vertical' && (
                    <div>
                      <span className="text-gray-500">Lift:</span>
                      <span className="ml-2 text-gray-900">Full vertical</span>
                    </div>
                  )}
                  <div>
                    <span className="text-gray-500">Spring Cycles:</span>
                    <span className="ml-2 text-gray-900">{(door.targetCycles || 10000).toLocaleString()}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Shaft:</span>
                    <span className="ml-2 text-gray-900 capitalize">{door.shaftType || 'auto'}</span>
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
            </div>
          </div>
        ))}
      </div>

      {/* Error Messages */}
      {errors.pricing && (
        <div className="bg-red-50 border border-red-200 rounded-md p-3">
          <p className="text-sm text-red-700">{errors.pricing}</p>
        </div>
      )}
      {errors.submit && (
        <div className="bg-red-50 border border-red-200 rounded-md p-3">
          <p className="text-sm text-red-700">{errors.submit}</p>
        </div>
      )}

      {/* Pricing Display */}
      {pricingData && pricingData.pricing && (
        <QuotePricingDisplay
          pricing={pricingData.pricing}
          linePricing={pricingData.line_pricing}
          linesFailed={pricingData.lines_failed}
          bcQuoteNumber={pricingData.bc_quote_number}
          doorResults={pricingData.door_results}
        />
      )}

      {/* Action Buttons */}
      <div className="space-y-3">
        {/* Get Pricing Button (for BC-linked accounts) */}
        {isBCLinked && !pricingData && (
          <button
            onClick={onGetPricing}
            disabled={pricingLoading || !quoteName.trim()}
            className="w-full inline-flex justify-center items-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {pricingLoading ? (
              <>
                <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Generating Pricing...
              </>
            ) : (
              'Get Quote Pricing'
            )}
          </button>
        )}

        {/* Confirm & Submit (after pricing is loaded) */}
        {pricingData && pricingData.pricing && (
          <button
            onClick={onConfirmSubmit}
            disabled={isSaving}
            className="w-full inline-flex justify-center items-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSaving ? (
              <>
                <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Submitting...
              </>
            ) : (
              'Confirm & Submit Quote'
            )}
          </button>
        )}

        {/* Save as Draft (always available) */}
        <button
          onClick={onSave}
          disabled={isSaving || !quoteName.trim()}
          className={`w-full inline-flex justify-center items-center px-6 py-3 border text-base font-medium rounded-md shadow-sm disabled:opacity-50 disabled:cursor-not-allowed ${
            pricingData
              ? 'border-gray-300 text-gray-700 bg-white hover:bg-gray-50'
              : 'border-transparent text-white bg-odc-600 hover:bg-odc-700'
          }`}
        >
          {isSaving && !pricingData ? (
            <>
              <svg className="animate-spin -ml-1 mr-3 h-5 w-5" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Saving...
            </>
          ) : (
            'Save as Draft'
          )}
        </button>
      </div>

      {/* Helper text */}
      <p className="text-xs text-gray-500 text-center">
        {isBCLinked
          ? 'Get pricing to see your customer-specific prices before submitting.'
          : 'Save your quote as a draft. Contact support to link your account for pricing.'}
      </p>
    </div>
  )
}

export default QuoteBuilder
