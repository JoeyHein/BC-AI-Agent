import { useState, useEffect } from 'react'
import { customersApi } from '../api/client'

/**
 * Admin panel for managing per-customer installation pricing.
 * Embedded in CustomerDetail when viewing a customer (especially home builders).
 */
function InstallPricingPanel({ customerId }) {
  const [pricing, setPricing] = useState({
    residential_small: '',
    residential_medium: '',
    residential_large: '',
    commercial_base_rate: '',
    commercial_sqft_rate: '',
    travel_rate_per_km: '',
    max_auto_height: 168,
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [hasData, setHasData] = useState(false)

  useEffect(() => {
    loadPricing()
  }, [customerId])

  async function loadPricing() {
    setLoading(true)
    setError(null)
    try {
      const response = await customersApi.getInstallPricing(customerId)
      const data = response.data?.install_pricing
      if (data) {
        setPricing({
          residential_small: data.residential_small ?? '',
          residential_medium: data.residential_medium ?? '',
          residential_large: data.residential_large ?? '',
          commercial_base_rate: data.commercial_base_rate ?? '',
          commercial_sqft_rate: data.commercial_sqft_rate ?? '',
          travel_rate_per_km: data.travel_rate_per_km ?? '',
          max_auto_height: data.max_auto_height ?? 168,
        })
        setHasData(true)
      }
    } catch (err) {
      if (err.response?.status === 404) {
        setHasData(false)
      } else {
        setError('Failed to load install pricing')
      }
    } finally {
      setLoading(false)
    }
  }

  function handleChange(field, value) {
    setPricing(prev => ({
      ...prev,
      [field]: value === '' ? '' : parseFloat(value),
    }))
    setSuccess(null)
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    setSuccess(null)

    try {
      await customersApi.setInstallPricing(customerId, {
        residential_small: pricing.residential_small === '' ? null : pricing.residential_small,
        residential_medium: pricing.residential_medium === '' ? null : pricing.residential_medium,
        residential_large: pricing.residential_large === '' ? null : pricing.residential_large,
        commercial_base_rate: pricing.commercial_base_rate === '' ? null : pricing.commercial_base_rate,
        commercial_sqft_rate: pricing.commercial_sqft_rate === '' ? null : pricing.commercial_sqft_rate,
        travel_rate_per_km: pricing.travel_rate_per_km === '' ? null : pricing.travel_rate_per_km,
        max_auto_height: pricing.max_auto_height || 168,
      })
      setSuccess('Install pricing saved')
      setHasData(true)
      setTimeout(() => setSuccess(null), 3000)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save install pricing')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="border-t border-gray-200 pt-4">
        <h4 className="text-sm font-medium text-gray-900 mb-2">Installation Pricing</h4>
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-odc-600"></div>
          Loading...
        </div>
      </div>
    )
  }

  return (
    <div className="border-t border-gray-200 pt-4">
      <h4 className="text-sm font-medium text-gray-900 mb-3">Installation Pricing</h4>

      {error && (
        <div className="mb-3 rounded-md bg-red-50 p-2">
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}
      {success && (
        <div className="mb-3 rounded-md bg-green-50 p-2">
          <p className="text-xs text-green-700">{success}</p>
        </div>
      )}

      {!hasData && !error && (
        <p className="text-xs text-gray-400 mb-3">
          No install pricing configured. Fill in rates below and save.
        </p>
      )}

      {/* Residential Rates */}
      <div className="mb-4">
        <p className="text-xs font-medium text-gray-500 uppercase mb-2">Residential Flat Rates</p>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="block text-xs text-gray-500 mb-0.5">Small (&le;90 sqft)</label>
            <div className="flex items-center">
              <span className="text-xs text-gray-400 mr-1">$</span>
              <input
                type="number" min="0" step="0.01"
                value={pricing.residential_small}
                onChange={(e) => handleChange('residential_small', e.target.value)}
                placeholder="0.00"
                className="w-full border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-0.5">Medium (91-130 sqft)</label>
            <div className="flex items-center">
              <span className="text-xs text-gray-400 mr-1">$</span>
              <input
                type="number" min="0" step="0.01"
                value={pricing.residential_medium}
                onChange={(e) => handleChange('residential_medium', e.target.value)}
                placeholder="0.00"
                className="w-full border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-0.5">Large (131-150 sqft)</label>
            <div className="flex items-center">
              <span className="text-xs text-gray-400 mr-1">$</span>
              <input
                type="number" min="0" step="0.01"
                value={pricing.residential_large}
                onChange={(e) => handleChange('residential_large', e.target.value)}
                placeholder="0.00"
                className="w-full border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Commercial Rates */}
      <div className="mb-4">
        <p className="text-xs font-medium text-gray-500 uppercase mb-2">Commercial Rates</p>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-xs text-gray-500 mb-0.5">Base rate (&le;100 sqft)</label>
            <div className="flex items-center">
              <span className="text-xs text-gray-400 mr-1">$</span>
              <input
                type="number" min="0" step="0.01"
                value={pricing.commercial_base_rate}
                onChange={(e) => handleChange('commercial_base_rate', e.target.value)}
                placeholder="0.00"
                className="w-full border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-0.5">Per sqft (above 100 sqft)</label>
            <div className="flex items-center">
              <span className="text-xs text-gray-400 mr-1">$</span>
              <input
                type="number" min="0" step="0.01"
                value={pricing.commercial_sqft_rate}
                onChange={(e) => handleChange('commercial_sqft_rate', e.target.value)}
                placeholder="0.00"
                className="w-full border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Travel */}
      <div className="mb-4">
        <p className="text-xs font-medium text-gray-500 uppercase mb-2">Travel</p>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-xs text-gray-500 mb-0.5">Rate per km (round trip)</label>
            <div className="flex items-center">
              <span className="text-xs text-gray-400 mr-1">$</span>
              <input
                type="number" min="0" step="0.01"
                value={pricing.travel_rate_per_km}
                onChange={(e) => handleChange('travel_rate_per_km', e.target.value)}
                placeholder="0.00"
                className="w-full border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-0.5">Max auto-quote height (inches)</label>
            <input
              type="number" min="0" step="1"
              value={pricing.max_auto_height}
              onChange={(e) => handleChange('max_auto_height', e.target.value)}
              placeholder="168"
              className="w-full border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
            />
            <p className="text-xs text-gray-400 mt-0.5">Default: 168 (14'). Doors taller require custom quote.</p>
          </div>
        </div>
      </div>

      <button
        onClick={handleSave}
        disabled={saving}
        className={`inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md shadow-sm text-white ${
          saving ? 'bg-gray-400 cursor-not-allowed' : 'bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500'
        }`}
      >
        {saving ? 'Saving...' : 'Save Install Pricing'}
      </button>
    </div>
  )
}

export default InstallPricingPanel
