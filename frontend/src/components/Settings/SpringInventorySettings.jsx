import { useState, useEffect } from 'react'
import { settingsApi } from '../../api/client'

function SpringInventorySettings() {
  const [inventory, setInventory] = useState({})
  const [availableSizes, setAvailableSizes] = useState({})
  const [coils, setCoils] = useState([])
  const [expandedCoil, setExpandedCoil] = useState('2.0')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [successMessage, setSuccessMessage] = useState(null)
  const [hasChanges, setHasChanges] = useState(false)

  // Fetch available sizes and current inventory on mount
  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      setLoading(true)
      setError(null)

      // Fetch both in parallel
      const [sizesResponse, inventoryResponse] = await Promise.all([
        settingsApi.getAvailableSpringSizes(),
        settingsApi.getSpringInventory()
      ])

      if (sizesResponse.data.success) {
        setCoils(sizesResponse.data.data.coils)
        setAvailableSizes(sizesResponse.data.data.wireSizes)
      }

      if (inventoryResponse.data.success) {
        setInventory(inventoryResponse.data.data.inventory)
      }
    } catch (err) {
      console.error('Error loading spring data:', err)
      setError('Failed to load spring data. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const toggleWireSize = (coilId, wireSize) => {
    setInventory(prev => {
      const coilSizes = prev[coilId] || []
      let newSizes
      if (coilSizes.includes(wireSize)) {
        newSizes = coilSizes.filter(w => w !== wireSize)
      } else {
        newSizes = [...coilSizes, wireSize].sort((a, b) => parseFloat(a) - parseFloat(b))
      }
      return { ...prev, [coilId]: newSizes }
    })
    setHasChanges(true)
    setSuccessMessage(null)
  }

  const selectAllForCoil = (coilId) => {
    const allSizes = (availableSizes[coilId] || []).map(w => w.diameterFormatted)
    setInventory(prev => ({ ...prev, [coilId]: allSizes }))
    setHasChanges(true)
    setSuccessMessage(null)
  }

  const clearAllForCoil = (coilId) => {
    setInventory(prev => ({ ...prev, [coilId]: [] }))
    setHasChanges(true)
    setSuccessMessage(null)
  }

  const saveInventory = async () => {
    try {
      setSaving(true)
      setError(null)

      const response = await settingsApi.updateSpringInventory(inventory)

      if (response.data.success) {
        setSuccessMessage(response.data.message)
        setHasChanges(false)
        // Clear success message after 3 seconds
        setTimeout(() => setSuccessMessage(null), 3000)
      }
    } catch (err) {
      console.error('Error saving inventory:', err)
      setError('Failed to save inventory settings. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const getTotalSelected = () => {
    return Object.values(inventory).reduce((sum, sizes) => sum + sizes.length, 0)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
        <span className="ml-3 text-gray-500">Loading spring data...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header with Save Button */}
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Spring Wire Inventory</h2>
          <p className="mt-1 text-sm text-gray-500">
            Select which wire sizes you carry in stock for each coil diameter.
            The spring calculator will prioritize these sizes when making recommendations.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {hasChanges && (
            <span className="text-sm text-amber-600">Unsaved changes</span>
          )}
          <button
            onClick={saveInventory}
            disabled={saving || !hasChanges}
            className={`
              inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white
              ${saving || !hasChanges
                ? 'bg-indigo-300 cursor-not-allowed'
                : 'bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500'
              }
            `}
          >
            {saving ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                Saving...
              </>
            ) : (
              'Save Changes'
            )}
          </button>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <p className="text-sm text-red-700">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Success Message */}
      {successMessage && (
        <div className="bg-green-50 border border-green-200 rounded-md p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <p className="text-sm text-green-700">{successMessage}</p>
            </div>
          </div>
        </div>
      )}

      {/* Summary Stats */}
      <div className="bg-gray-50 rounded-lg p-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-indigo-600">{getTotalSelected()}</div>
            <div className="text-xs text-gray-500">Wire Sizes Selected</div>
          </div>
          {coils.map(coil => (
            <div key={coil.id} className="text-center">
              <div className="text-lg font-semibold text-gray-700">
                {(inventory[coil.id] || []).length} / {coil.wireSizeCount}
              </div>
              <div className="text-xs text-gray-500">{coil.name} Coil</div>
            </div>
          ))}
        </div>
      </div>

      {/* Coil Diameter Sections */}
      <div className="space-y-4">
        {coils.map(coil => (
          <div key={coil.id} className="border border-gray-200 rounded-lg overflow-hidden">
            {/* Coil Header */}
            <button
              onClick={() => setExpandedCoil(expandedCoil === coil.id ? null : coil.id)}
              className="w-full px-4 py-3 flex justify-between items-center bg-gray-50 hover:bg-gray-100 transition-colors"
            >
              <div className="flex items-center">
                <svg
                  className={`h-5 w-5 text-gray-400 transform transition-transform ${
                    expandedCoil === coil.id ? 'rotate-90' : ''
                  }`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
                <span className="ml-2 font-medium text-gray-900">{coil.displayName}</span>
                <span className="ml-2 text-sm text-gray-500">({coil.description})</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-gray-500">
                  {(inventory[coil.id] || []).length} of {coil.wireSizeCount} selected
                </span>
                <div className="h-2 w-24 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 transition-all"
                    style={{
                      width: `${((inventory[coil.id] || []).length / coil.wireSizeCount) * 100}%`
                    }}
                  />
                </div>
              </div>
            </button>

            {/* Wire Sizes Grid */}
            {expandedCoil === coil.id && (
              <div className="px-4 pb-4 pt-2 border-t border-gray-200">
                {/* Quick Actions */}
                <div className="flex gap-2 mb-4">
                  <button
                    onClick={() => selectAllForCoil(coil.id)}
                    className="text-sm text-indigo-600 hover:text-indigo-800 font-medium"
                  >
                    Select All
                  </button>
                  <span className="text-gray-300">|</span>
                  <button
                    onClick={() => clearAllForCoil(coil.id)}
                    className="text-sm text-gray-500 hover:text-gray-700 font-medium"
                  >
                    Clear All
                  </button>
                </div>

                {/* Wire Size Buttons */}
                <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 gap-2">
                  {(availableSizes[coil.id] || []).map(wire => {
                    const isSelected = (inventory[coil.id] || []).includes(wire.diameterFormatted)
                    return (
                      <button
                        key={wire.diameter}
                        onClick={() => toggleWireSize(coil.id, wire.diameterFormatted)}
                        className={`
                          p-2 rounded-md text-sm font-medium transition-all border-2
                          ${isSelected
                            ? 'bg-indigo-100 border-indigo-500 text-indigo-700 shadow-sm'
                            : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                          }
                        `}
                        title={`Rate: ${wire.rate}, Lift/Turn: ${wire.liftPerTurn}`}
                      >
                        {wire.diameterFormatted}"
                      </button>
                    )
                  })}
                </div>

                {/* Legend */}
                <div className="mt-4 pt-3 border-t border-gray-100 text-xs text-gray-500">
                  <span className="inline-flex items-center mr-4">
                    <span className="w-3 h-3 bg-indigo-100 border-2 border-indigo-500 rounded mr-1"></span>
                    In Stock
                  </span>
                  <span className="inline-flex items-center">
                    <span className="w-3 h-3 bg-white border-2 border-gray-200 rounded mr-1"></span>
                    Not Stocked
                  </span>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Info Box */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-blue-800">How this works</h3>
            <div className="mt-2 text-sm text-blue-700">
              <p>
                When the door configurator calculates spring recommendations, it will prioritize
                wire sizes that you have marked as "in stock" here. If no stocked sizes match
                the door requirements, the system will suggest the closest available options
                and indicate they may need to be ordered.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default SpringInventorySettings
