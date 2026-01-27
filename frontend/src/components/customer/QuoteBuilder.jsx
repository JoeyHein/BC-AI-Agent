import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { savedQuotesApi, customerDoorConfigApi } from '../../api/customerClient'

function QuoteBuilder() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isEditing = !!id

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [config, setConfig] = useState({
    door_type: 'residential',
    width: 96,
    height: 84,
    color: '',
    panel_design: '',
    window_type: 'none',
    track_type: 'standard',
    hardware: [],
    notes: ''
  })
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

  // Fetch door configuration options
  const { data: configOptions } = useQuery({
    queryKey: ['doorConfigOptions'],
    queryFn: async () => {
      const response = await customerDoorConfigApi.getFullConfig()
      return response.data
    }
  })

  // Load existing data
  useEffect(() => {
    if (existingQuote) {
      setName(existingQuote.name || '')
      setDescription(existingQuote.description || '')
      setConfig(existingQuote.config_data || config)
    }
  }, [existingQuote])

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

  const handleSave = async () => {
    // Validate
    const newErrors = {}
    if (!name.trim()) {
      newErrors.name = 'Quote name is required'
    }
    if (!config.width || config.width < 48 || config.width > 240) {
      newErrors.width = 'Width must be between 48" and 240"'
    }
    if (!config.height || config.height < 48 || config.height > 240) {
      newErrors.height = 'Height must be between 48" and 240"'
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors)
      return
    }

    setErrors({})
    setSaving(true)

    try {
      await saveMutation.mutateAsync({
        name: name.trim(),
        description: description.trim(),
        config_data: config
      })
    } catch (error) {
      console.error('Save error:', error)
      setErrors({ submit: error.response?.data?.detail || 'Failed to save quote' })
    } finally {
      setSaving(false)
    }
  }

  const updateConfig = (field, value) => {
    setConfig(prev => ({ ...prev, [field]: value }))
  }

  if (loadingQuote) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {isEditing ? 'Edit Quote' : 'New Quote'}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Configure your door and save it for later or submit for a quote
          </p>
        </div>
        <button
          onClick={() => navigate('/saved-quotes')}
          className="text-gray-500 hover:text-gray-700"
        >
          Cancel
        </button>
      </div>

      {errors.submit && (
        <div className="bg-red-50 p-4 rounded-md">
          <p className="text-red-700">{errors.submit}</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Configuration form */}
        <div className="lg:col-span-2 space-y-6">
          {/* Quote details */}
          <div className="bg-white shadow rounded-lg p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">Quote Details</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Quote Name *
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
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
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  placeholder="Any additional notes..."
                />
              </div>
            </div>
          </div>

          {/* Door dimensions */}
          <div className="bg-white shadow rounded-lg p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">Door Dimensions</h2>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Width (inches) *
                </label>
                <input
                  type="number"
                  value={config.width}
                  onChange={(e) => updateConfig('width', parseInt(e.target.value) || '')}
                  className={`mt-1 block w-full rounded-md shadow-sm sm:text-sm ${
                    errors.width ? 'border-red-300' : 'border-gray-300'
                  } focus:border-blue-500 focus:ring-blue-500`}
                  min={48}
                  max={240}
                />
                {errors.width && <p className="mt-1 text-sm text-red-600">{errors.width}</p>}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Height (inches) *
                </label>
                <input
                  type="number"
                  value={config.height}
                  onChange={(e) => updateConfig('height', parseInt(e.target.value) || '')}
                  className={`mt-1 block w-full rounded-md shadow-sm sm:text-sm ${
                    errors.height ? 'border-red-300' : 'border-gray-300'
                  } focus:border-blue-500 focus:ring-blue-500`}
                  min={48}
                  max={240}
                />
                {errors.height && <p className="mt-1 text-sm text-red-600">{errors.height}</p>}
              </div>
            </div>
          </div>

          {/* Door type */}
          <div className="bg-white shadow rounded-lg p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">Door Type</h2>
            <div className="grid grid-cols-2 gap-4">
              {['residential', 'commercial'].map((type) => (
                <button
                  key={type}
                  onClick={() => updateConfig('door_type', type)}
                  className={`p-4 border-2 rounded-lg text-left ${
                    config.door_type === type
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <p className="font-medium capitalize">{type}</p>
                  <p className="text-sm text-gray-500">
                    {type === 'residential' ? 'For home garages' : 'For commercial buildings'}
                  </p>
                </button>
              ))}
            </div>
          </div>

          {/* Color selection */}
          <div className="bg-white shadow rounded-lg p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">Color</h2>
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
              {['White', 'Almond', 'Brown', 'Sandstone', 'Gray', 'Black', 'Custom'].map((color) => (
                <button
                  key={color}
                  onClick={() => updateConfig('color', color)}
                  className={`p-3 border-2 rounded-lg text-center ${
                    config.color === color
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  {color}
                </button>
              ))}
            </div>
          </div>

          {/* Window options */}
          <div className="bg-white shadow rounded-lg p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">Windows</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {['none', 'plain', 'stockton', 'cascade', 'sherwood'].map((window) => (
                <button
                  key={window}
                  onClick={() => updateConfig('window_type', window)}
                  className={`p-3 border-2 rounded-lg text-center capitalize ${
                    config.window_type === window
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  {window === 'none' ? 'No Windows' : window}
                </button>
              ))}
            </div>
          </div>

          {/* Additional notes */}
          <div className="bg-white shadow rounded-lg p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">Additional Notes</h2>
            <textarea
              value={config.notes}
              onChange={(e) => updateConfig('notes', e.target.value)}
              rows={4}
              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              placeholder="Any special requirements, installation notes, or questions..."
            />
          </div>
        </div>

        {/* Summary sidebar */}
        <div className="lg:col-span-1">
          <div className="bg-white shadow rounded-lg p-6 sticky top-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">Summary</h2>
            <dl className="space-y-3 text-sm">
              <div className="flex justify-between">
                <dt className="text-gray-500">Door Type</dt>
                <dd className="font-medium capitalize">{config.door_type}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Size</dt>
                <dd className="font-medium">{config.width}" x {config.height}"</dd>
              </div>
              {config.color && (
                <div className="flex justify-between">
                  <dt className="text-gray-500">Color</dt>
                  <dd className="font-medium">{config.color}</dd>
                </div>
              )}
              <div className="flex justify-between">
                <dt className="text-gray-500">Windows</dt>
                <dd className="font-medium capitalize">
                  {config.window_type === 'none' ? 'None' : config.window_type}
                </dd>
              </div>
            </dl>

            <div className="mt-6 pt-6 border-t border-gray-200 space-y-3">
              <button
                onClick={handleSave}
                disabled={saving}
                className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
              >
                {saving ? 'Saving...' : isEditing ? 'Update Quote' : 'Save Quote'}
              </button>
              <button
                onClick={() => navigate('/saved-quotes')}
                className="w-full flex justify-center py-2 px-4 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                Cancel
              </button>
            </div>

            <p className="mt-4 text-xs text-gray-500 text-center">
              Your quote will be saved as a draft. You can submit it later for processing.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default QuoteBuilder
