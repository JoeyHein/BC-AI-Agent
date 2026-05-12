import { useState, useEffect, useRef } from 'react'
import { installPricingApi } from '../../api/customerClient'

/**
 * Installation town input for home builder quotes.
 *
 * Collects the installation town and previews the travel cost inline
 * (backend resolves via cached static dict, then Google Distance Matrix).
 * The town value is passed up to the door config so it lands on the BC
 * quote when the customer submits.
 */
function InstallPriceEstimate({ town: externalTown, onTownChange }) {
  const [town, setTown] = useState(externalTown || '')
  const [quote, setQuote] = useState(null)       // { distance_km, travel_price, source } | null
  const [loading, setLoading] = useState(false)
  const debounceRef = useRef(null)

  // Debounce live travel lookup so we don't fire on every keystroke.
  useEffect(() => {
    const trimmed = (town || '').trim()
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!trimmed) {
      setQuote(null)
      setLoading(false)
      return
    }
    setLoading(true)
    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await installPricingApi.travelQuote(trimmed)
        setQuote(data)
      } catch {
        setQuote({ source: 'unknown', distance_km: null, travel_price: 0 })
      } finally {
        setLoading(false)
      }
    }, 600)
    return () => debounceRef.current && clearTimeout(debounceRef.current)
  }, [town])

  function handleChange(e) {
    setTown(e.target.value)
    onTownChange?.(e.target.value)
  }

  return (
    <div className="border border-blue-200 bg-blue-50 rounded-lg p-4">
      <h4 className="text-sm font-medium text-gray-900 mb-2 flex items-center gap-2">
        <svg className="h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
        </svg>
        Installation
      </h4>
      <p className="text-xs text-gray-500 mb-3">
        Installation is included on every quote. Enter the installation town so we can include travel.
      </p>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Installation Town <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={town}
          onChange={handleChange}
          placeholder="e.g., Calgary, Lethbridge, Regina..."
          required
          aria-required="true"
          className={`block w-full md:w-64 border rounded-md shadow-sm py-1.5 px-3 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500 ${
            town?.trim() ? 'border-gray-300' : 'border-red-300 bg-red-50'
          }`}
        />
        <p className="text-xs text-gray-400 mt-0.5">
          Required. Use "Medicine Hat" for local installs (no travel charge).
        </p>

        {/* Inline travel preview — appears once the customer enters a town */}
        {town?.trim() && (
          <div className="mt-2 text-xs">
            {loading && <span className="text-gray-500">Looking up distance…</span>}
            {!loading && quote && quote.distance_km != null && (
              <span className="text-gray-700">
                Travel: <span className="font-medium">${quote.travel_price.toFixed(2)}</span>
                {' '}({quote.distance_km.toFixed(0)} km from Medicine Hat)
              </span>
            )}
            {!loading && quote && quote.distance_km == null && (
              <span className="text-amber-700">
                Could not auto-resolve "{town}" — travel will be quoted manually.
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default InstallPriceEstimate
