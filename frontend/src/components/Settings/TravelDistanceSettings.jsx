import { useState, useEffect } from 'react'
import { customersApi } from '../../api/client'

/**
 * Admin settings panel for managing town-to-distance lookup table.
 * Distances are from Medicine Hat, AB (where OPENDC is located).
 */
function TravelDistanceSettings() {
  const [distances, setDistances] = useState({}) // { "Calgary": 300, "Lethbridge": 170, ... }
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [hasChanges, setHasChanges] = useState(false)

  // New row form
  const [newTown, setNewTown] = useState('')
  const [newDistance, setNewDistance] = useState('')

  useEffect(() => {
    loadDistances()
  }, [])

  async function loadDistances() {
    setLoading(true)
    setError(null)
    try {
      const response = await customersApi.getTravelDistances()
      setDistances(response.data?.distances || response.data || {})
    } catch (err) {
      if (err.response?.status !== 404) {
        setError('Failed to load travel distances')
      }
    } finally {
      setLoading(false)
    }
  }

  function handleDistanceChange(town, value) {
    setDistances(prev => ({
      ...prev,
      [town]: value === '' ? '' : parseFloat(value),
    }))
    setHasChanges(true)
    setSuccess(null)
  }

  function handleRemove(town) {
    setDistances(prev => {
      const next = { ...prev }
      delete next[town]
      return next
    })
    setHasChanges(true)
    setSuccess(null)
  }

  function handleAdd() {
    const town = newTown.trim()
    const dist = parseFloat(newDistance)
    if (!town || isNaN(dist) || dist < 0) return

    setDistances(prev => ({
      ...prev,
      [town]: dist,
    }))
    setNewTown('')
    setNewDistance('')
    setHasChanges(true)
    setSuccess(null)
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    setSuccess(null)

    // Clean up any empty values
    const cleaned = {}
    for (const [town, dist] of Object.entries(distances)) {
      if (town.trim() && dist !== '' && !isNaN(dist)) {
        cleaned[town.trim()] = parseFloat(dist)
      }
    }

    try {
      await customersApi.setTravelDistances({ distances: cleaned })
      setDistances(cleaned)
      setSuccess('Travel distances saved successfully')
      setHasChanges(false)
      setTimeout(() => setSuccess(null), 3000)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save travel distances')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-odc-600"></div>
        <span className="ml-3 text-gray-500">Loading travel distances...</span>
      </div>
    )
  }

  const sortedTowns = Object.keys(distances).sort((a, b) => a.localeCompare(b))

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Travel Distances</h2>
          <p className="mt-1 text-sm text-gray-500">
            Approximate driving distances from Medicine Hat, AB. Used to calculate travel charges for installation.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {hasChanges && (
            <span className="text-sm text-amber-600">Unsaved changes</span>
          )}
          <button
            onClick={handleSave}
            disabled={saving || !hasChanges}
            className={`inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white ${
              saving || !hasChanges
                ? 'bg-gray-300 cursor-not-allowed'
                : 'bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500'
            }`}
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className="rounded-md bg-red-50 p-4">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}
      {success && (
        <div className="rounded-md bg-green-50 p-4">
          <p className="text-sm text-green-800">{success}</p>
        </div>
      )}

      {/* Distance Table */}
      <div className="overflow-hidden border border-gray-200 rounded-lg">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Town / City
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider w-40">
                Distance (km)
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider w-40">
                Round Trip (km)
              </th>
              <th className="px-4 py-3 w-16" />
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {sortedTowns.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-sm text-gray-400">
                  No towns configured. Add towns below.
                </td>
              </tr>
            ) : (
              sortedTowns.map(town => (
                <tr key={town}>
                  <td className="px-4 py-3 text-sm text-gray-900">{town}</td>
                  <td className="px-4 py-3 text-center">
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={distances[town]}
                      onChange={(e) => handleDistanceChange(town, e.target.value)}
                      className="w-24 text-center border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                    />
                  </td>
                  <td className="px-4 py-3 text-center text-sm text-gray-500">
                    {distances[town] !== '' && !isNaN(distances[town]) ? (distances[town] * 2) : '-'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleRemove(town)}
                      className="text-red-400 hover:text-red-600 text-xs"
                      title="Remove"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Add row */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="Town name (e.g., Calgary)"
          value={newTown}
          onChange={(e) => setNewTown(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          className="block w-56 border border-gray-300 rounded-md shadow-sm py-1.5 px-3 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
        />
        <div className="flex items-center gap-1">
          <input
            type="number"
            min="0"
            step="1"
            placeholder="km"
            value={newDistance}
            onChange={(e) => setNewDistance(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            className="w-24 text-center border border-gray-300 rounded-md shadow-sm py-1.5 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
          />
          <span className="text-sm text-gray-500">km</span>
        </div>
        <button
          onClick={handleAdd}
          disabled={!newTown.trim() || !newDistance}
          className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-40"
        >
          + Add
        </button>
      </div>

      {/* Reference note */}
      <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-600">
        <strong>Travel Pricing Formula:</strong>{' '}
        <code className="bg-white px-1.5 py-0.5 rounded border text-xs font-mono">
          travel_cost = rate_per_km x distance_km x 2 (round trip)
        </code>
        <p className="mt-2 text-xs text-gray-500">
          Distances are one-way from Medicine Hat, AB. The travel charge is computed as round trip (x2).
        </p>
      </div>
    </div>
  )
}

export default TravelDistanceSettings
