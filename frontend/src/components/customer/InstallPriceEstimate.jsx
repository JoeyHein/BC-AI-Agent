import { useState, useEffect, useRef } from 'react'
import { installPricingApi } from '../../api/customerClient'

/**
 * Reusable install price estimate component.
 * Shows installation pricing for home builder customers based on door dimensions.
 *
 * Props:
 *   doorWidthInches  - door width in inches
 *   doorHeightInches - door height in inches
 *   doorType         - 'residential' or 'commercial'
 */
function InstallPriceEstimate({ doorWidthInches, doorHeightInches, doorType, town: externalTown, onTownChange }) {
  const [town, setTown] = useState(externalTown || '')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const debounceRef = useRef(null)

  // Debounced calculation whenever inputs change
  useEffect(() => {
    if (!doorWidthInches || !doorHeightInches || !doorType) {
      setResult(null)
      setError(null)
      return
    }

    if (debounceRef.current) clearTimeout(debounceRef.current)

    debounceRef.current = setTimeout(() => {
      calculateInstall()
    }, 500)

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [doorWidthInches, doorHeightInches, doorType, town])

  async function calculateInstall() {
    setLoading(true)
    setError(null)

    try {
      const response = await installPricingApi.calculate({
        door_width_inches: doorWidthInches,
        door_height_inches: doorHeightInches,
        door_type: doorType,
        town: town || null,
      })
      setResult(response.data)
    } catch (err) {
      const detail = err.response?.data?.detail
      if (err.response?.status === 404 || (typeof detail === 'string' && detail.toLowerCase().includes('no install pricing'))) {
        // No install pricing configured for this customer -- hide quietly
        setResult(null)
        setError(null)
      } else {
        setError(detail || 'Failed to calculate install pricing')
        setResult(null)
      }
    } finally {
      setLoading(false)
    }
  }

  // Don't render anything if there's no result and no error (pricing not configured)
  if (!result && !error && !loading) return null

  const sqft = ((doorWidthInches * doorHeightInches) / 144).toFixed(1)

  return (
    <div className="border border-blue-200 bg-blue-50 rounded-lg p-4">
      <h4 className="text-sm font-medium text-gray-900 mb-3 flex items-center gap-2">
        <svg className="h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
        </svg>
        Installation Estimate
      </h4>

      {/* Town selector */}
      <div className="mb-3">
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Installation Town (for travel cost)
        </label>
        <input
          type="text"
          value={town}
          onChange={(e) => { setTown(e.target.value); onTownChange?.(e.target.value); }}
          placeholder="e.g., Calgary, Lethbridge, Brooks..."
          className="block w-full md:w-64 border border-gray-300 rounded-md shadow-sm py-1.5 px-3 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
        />
        <p className="text-xs text-gray-400 mt-0.5">Leave blank to see install only (no travel)</p>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-odc-600"></div>
          Calculating...
        </div>
      )}

      {error && (
        <div className="text-sm text-red-600">{error}</div>
      )}

      {result && !loading && (
        <div className="space-y-2">
          {result.custom_quote_required ? (
            <div className="bg-amber-50 border border-amber-200 rounded-md p-3">
              <p className="text-sm font-medium text-amber-800">Custom Quote Required</p>
              <p className="text-xs text-amber-700 mt-1">
                {result.reason || 'This door exceeds standard installation parameters. Please contact us for a custom installation quote.'}
              </p>
            </div>
          ) : (
            <>
              {/* Breakdown */}
              <div className="text-sm space-y-1">
                <div className="flex justify-between text-gray-600">
                  <span>Door area</span>
                  <span>{sqft} sqft</span>
                </div>

                {result.breakdown?.rate_tier && (
                  <div className="flex justify-between text-gray-600">
                    <span>Rate tier</span>
                    <span className="capitalize">{result.breakdown.rate_tier}</span>
                  </div>
                )}

                <div className="flex justify-between text-gray-700">
                  <span>Installation</span>
                  <span>${Number(result.install_price || 0).toFixed(2)}</span>
                </div>

                {result.travel_price > 0 && (
                  <div className="flex justify-between text-gray-700">
                    <span>Travel ({result.breakdown?.distance_km ? `${result.breakdown.distance_km} km x 2` : town})</span>
                    <span>${Number(result.travel_price).toFixed(2)}</span>
                  </div>
                )}

                {town && result.travel_price === 0 && !result.breakdown?.distance_km && (
                  <div className="flex justify-between text-gray-400 italic text-xs">
                    <span>Travel</span>
                    <span>Town not found in distance table</span>
                  </div>
                )}

                <div className="flex justify-between text-gray-900 font-medium border-t border-blue-200 pt-1 mt-1">
                  <span>Total Install Estimate</span>
                  <span>${Number(result.total || 0).toFixed(2)}</span>
                </div>
              </div>

              <p className="text-xs text-gray-400 mt-2">
                Estimate only. Final price may vary based on site conditions.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default InstallPriceEstimate
