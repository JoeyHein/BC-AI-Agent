import { useState, useEffect } from 'react'
import apiClient from '../../api/client'
import { customersApi } from '../../api/client'

function InstallPricingSettings() {
  const [customers, setCustomers] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedCustomerId, setSelectedCustomerId] = useState(null)
  const [pricing, setPricing] = useState(null)
  const [saving, setSaving] = useState(false)
  const [pricingLoading, setPricingLoading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  useEffect(() => {
    loadCustomers()
  }, [])

  async function loadCustomers() {
    setLoading(true)
    try {
      const response = await apiClient.get('/api/admin/customers')
      const all = response.data || []
      setCustomers(all)
    } catch (err) {
      setError('Failed to load customers')
    } finally {
      setLoading(false)
    }
  }

  async function loadPricing(customerId) {
    setPricingLoading(true)
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
      } else {
        setPricing({
          residential_small: '',
          residential_medium: '',
          residential_large: '',
          commercial_base_rate: '',
          commercial_sqft_rate: '',
          travel_rate_per_km: '',
          max_auto_height: 168,
        })
      }
    } catch (err) {
      setPricing({
        residential_small: '',
        residential_medium: '',
        residential_large: '',
        commercial_base_rate: '',
        commercial_sqft_rate: '',
        travel_rate_per_km: '',
        max_auto_height: 168,
      })
    } finally {
      setPricingLoading(false)
    }
  }

  function selectCustomer(id) {
    setSelectedCustomerId(id)
    setSuccess(null)
    setError(null)
    loadPricing(id)
  }

  function handleChange(field, value) {
    setPricing(prev => ({ ...prev, [field]: value === '' ? '' : parseFloat(value) }))
    setSuccess(null)
  }

  async function handleSave() {
    if (!selectedCustomerId) return
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      await customersApi.setInstallPricing(selectedCustomerId, {
        residential_small: pricing.residential_small === '' ? null : pricing.residential_small,
        residential_medium: pricing.residential_medium === '' ? null : pricing.residential_medium,
        residential_large: pricing.residential_large === '' ? null : pricing.residential_large,
        commercial_base_rate: pricing.commercial_base_rate === '' ? null : pricing.commercial_base_rate,
        commercial_sqft_rate: pricing.commercial_sqft_rate === '' ? null : pricing.commercial_sqft_rate,
        travel_rate_per_km: pricing.travel_rate_per_km === '' ? null : pricing.travel_rate_per_km,
        max_auto_height: pricing.max_auto_height || 168,
      })
      setSuccess('Install pricing saved successfully')
      setTimeout(() => setSuccess(null), 3000)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const homeBuilders = customers.filter(c => c.account_type === 'home_builder')
  const selectedCustomer = customers.find(c => c.id === selectedCustomerId)

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-medium text-gray-900">Installation Pricing</h2>
        <p className="text-sm text-gray-500">
          Set per-customer installation rates for home builders. Select a customer to configure their pricing.
        </p>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 p-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}
      {success && (
        <div className="rounded-md bg-green-50 p-3">
          <p className="text-sm text-green-700">{success}</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Customer list */}
        <div className="lg:col-span-1">
          <h3 className="text-sm font-medium text-gray-700 mb-2">
            Home Builder Customers ({homeBuilders.length})
          </h3>
          {homeBuilders.length === 0 ? (
            <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-500">
              No home builder customers found. Change a customer's account type to "Home Builder" in Customer Management first.
            </div>
          ) : (
            <div className="border border-gray-200 rounded-lg divide-y divide-gray-200 max-h-96 overflow-y-auto">
              {homeBuilders.map(c => (
                <button
                  key={c.id}
                  onClick={() => selectCustomer(c.id)}
                  className={`w-full text-left px-3 py-2.5 text-sm hover:bg-gray-50 transition-colors ${
                    selectedCustomerId === c.id ? 'bg-odc-50 border-l-2 border-odc-600' : ''
                  }`}
                >
                  <div className="font-medium text-gray-900">{c.name || c.email}</div>
                  <div className="text-xs text-gray-500">{c.bc_company_name || c.email}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Pricing form */}
        <div className="lg:col-span-2">
          {!selectedCustomerId ? (
            <div className="bg-gray-50 rounded-lg p-8 text-center text-sm text-gray-500">
              Select a home builder customer from the list to configure their installation pricing.
            </div>
          ) : pricingLoading ? (
            <div className="flex justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-odc-600"></div>
            </div>
          ) : pricing ? (
            <div className="border border-gray-200 rounded-lg p-5 space-y-5">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-900">
                  {selectedCustomer?.name || selectedCustomer?.email}
                </h3>
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800">
                  Home Builder
                </span>
              </div>

              {/* Residential Rates */}
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Residential Flat Rates</p>
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { key: 'residential_small', label: 'Small (\u226490 sqft)' },
                    { key: 'residential_medium', label: 'Medium (91-130 sqft)' },
                    { key: 'residential_large', label: 'Large (131-150 sqft)' },
                  ].map(({ key, label }) => (
                    <div key={key}>
                      <label className="block text-xs text-gray-500 mb-0.5">{label}</label>
                      <div className="relative">
                        <span className="absolute left-2 top-1.5 text-xs text-gray-400">$</span>
                        <input
                          type="number" min="0" step="0.01"
                          value={pricing[key]}
                          onChange={(e) => handleChange(key, e.target.value)}
                          placeholder="0.00"
                          className="w-full pl-5 pr-2 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                        />
                      </div>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-gray-400 mt-1">Residential doors over 150 sqft use commercial formula.</p>
              </div>

              {/* Commercial Rates */}
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Commercial Rates</p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-0.5">Base rate (&le;100 sqft)</label>
                    <div className="relative">
                      <span className="absolute left-2 top-1.5 text-xs text-gray-400">$</span>
                      <input
                        type="number" min="0" step="0.01"
                        value={pricing.commercial_base_rate}
                        onChange={(e) => handleChange('commercial_base_rate', e.target.value)}
                        placeholder="0.00"
                        className="w-full pl-5 pr-2 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-0.5">Per sqft (above 100 sqft)</label>
                    <div className="relative">
                      <span className="absolute left-2 top-1.5 text-xs text-gray-400">$</span>
                      <input
                        type="number" min="0" step="0.01"
                        value={pricing.commercial_sqft_rate}
                        onChange={(e) => handleChange('commercial_sqft_rate', e.target.value)}
                        placeholder="0.00"
                        className="w-full pl-5 pr-2 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Travel & Height */}
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Travel & Limits</p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-0.5">Travel rate per km (round trip)</label>
                    <div className="relative">
                      <span className="absolute left-2 top-1.5 text-xs text-gray-400">$</span>
                      <input
                        type="number" min="0" step="0.01"
                        value={pricing.travel_rate_per_km}
                        onChange={(e) => handleChange('travel_rate_per_km', e.target.value)}
                        placeholder="0.00"
                        className="w-full pl-5 pr-2 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
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
                      className="w-full py-1.5 px-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                    />
                    <p className="text-xs text-gray-400 mt-0.5">Default 168" (14'). Above = custom quote.</p>
                  </div>
                </div>
              </div>

              <button
                onClick={handleSave}
                disabled={saving}
                className={`w-full py-2 px-4 text-sm font-medium rounded-md text-white ${
                  saving ? 'bg-gray-400 cursor-not-allowed' : 'bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500'
                }`}
              >
                {saving ? 'Saving...' : 'Save Install Pricing'}
              </button>
            </div>
          ) : null}
        </div>
      </div>

      {/* Reference info */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h4 className="text-sm font-medium text-blue-800 mb-1">How Installation Pricing Works</h4>
        <ul className="text-xs text-blue-700 space-y-1 list-disc list-inside">
          <li><strong>Residential:</strong> Flat rate by door area — Small (&le;90 sqft), Medium (91-130 sqft), Large (131-150 sqft)</li>
          <li><strong>Residential &gt;150 sqft:</strong> Automatically uses commercial formula</li>
          <li><strong>Commercial:</strong> Base rate for first 100 sqft + per-sqft rate for area above 100</li>
          <li><strong>Height limit:</strong> Doors taller than max height require custom quoting (lift needed)</li>
          <li><strong>Travel:</strong> Rate per km x distance from Medicine Hat x 2 (round trip). Configure towns in Travel Distances tab.</li>
        </ul>
      </div>
    </div>
  )
}

export default InstallPricingSettings
