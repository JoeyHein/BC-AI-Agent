import { useState } from 'react'

/**
 * Installation town input for home builder quotes.
 * Collects the installation town (for travel cost calculation)
 * and passes it to the door config so it's included in the BC quote.
 *
 * Pricing is NOT shown here — it appears on the BC quote after submission.
 */
function InstallPriceEstimate({ town: externalTown, onTownChange }) {
  const [town, setTown] = useState(externalTown || '')

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
        Installation will be included on your quote. Enter the town for travel cost calculation.
      </p>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Installation Town
        </label>
        <input
          type="text"
          value={town}
          onChange={handleChange}
          placeholder="e.g., Calgary, Lethbridge, Regina..."
          className="block w-full md:w-64 border border-gray-300 rounded-md shadow-sm py-1.5 px-3 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
        />
        <p className="text-xs text-gray-400 mt-0.5">Leave blank if no travel required (local install)</p>
      </div>
    </div>
  )
}

export default InstallPriceEstimate
