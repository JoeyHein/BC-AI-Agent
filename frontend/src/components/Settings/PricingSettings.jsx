import { useState, useEffect } from 'react'
import { settingsApi } from '../../api/client'

const TIER_ORDER = ['gold', 'silver', 'bronze', 'retail']
const DOOR_TYPES = ['residential', 'commercial']

const TIER_COLORS = {
  gold: 'bg-amber-100 text-amber-800',
  silver: 'bg-gray-200 text-gray-700',
  bronze: 'bg-orange-100 text-orange-800',
  retail: 'bg-blue-100 text-blue-800',
}

function PricingSettings() {
  const [margins, setMargins] = useState({})
  const [adjustments, setAdjustments] = useState({})
  const [categories, setCategories] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [successMessage, setSuccessMessage] = useState(null)
  const [hasChanges, setHasChanges] = useState(false)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      setLoading(true)
      setError(null)

      const [tiersRes, adjRes, catRes] = await Promise.all([
        settingsApi.getPricingTiers(),
        settingsApi.getPricingCostAdjustments(),
        settingsApi.getPricingCategories(),
      ])

      if (tiersRes.data.success) setMargins(tiersRes.data.data.margins)
      if (adjRes.data.success) setAdjustments(adjRes.data.data.adjustments)
      if (catRes.data.success) setCategories(catRes.data.data)
    } catch (err) {
      console.error('Error loading pricing data:', err)
      setError('Failed to load pricing settings.')
    } finally {
      setLoading(false)
    }
  }

  const handleMarginChange = (doorType, tier, value) => {
    const num = value === '' ? '' : parseFloat(value)
    setMargins(prev => ({
      ...prev,
      [doorType]: {
        ...prev[doorType],
        [tier]: num,
      }
    }))
    setHasChanges(true)
    setSuccessMessage(null)
  }

  const handleAdjustmentChange = (code, field, value) => {
    setAdjustments(prev => ({
      ...prev,
      [code]: {
        ...prev[code],
        [field]: field === 'adjustment' ? (value === '' ? '' : parseFloat(value)) : value,
      }
    }))
    setHasChanges(true)
    setSuccessMessage(null)
  }

  const save = async () => {
    try {
      setSaving(true)
      setError(null)

      // Validate margins
      for (const doorType of DOOR_TYPES) {
        const tiers = margins[doorType] || {}
        for (const [tier, val] of Object.entries(tiers)) {
          if (val === '' || val < 0 || val > 99) {
            setError(`Margin for ${doorType}/${tier} must be 0-99%`)
            return
          }
        }
      }

      // Validate adjustments
      for (const [code, entry] of Object.entries(adjustments)) {
        const adj = entry?.adjustment ?? 0
        if (adj !== '' && (adj < -50 || adj > 100)) {
          setError(`Cost adjustment for ${code} must be -50% to +100%`)
          return
        }
      }

      await Promise.all([
        settingsApi.updatePricingTiers(margins),
        settingsApi.updatePricingCostAdjustments(adjustments),
      ])

      setSuccessMessage('Pricing settings saved successfully')
      setHasChanges(false)
      setTimeout(() => setSuccessMessage(null), 3000)
    } catch (err) {
      console.error('Error saving pricing settings:', err)
      setError(err.response?.data?.detail || 'Failed to save pricing settings.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-odc-600"></div>
        <span className="ml-3 text-gray-500">Loading pricing settings...</span>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Header with Save Button */}
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Pricing & Margins</h2>
          <p className="mt-1 text-sm text-gray-500">
            Configure margin tiers and cost adjustments for door quote pricing.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {hasChanges && (
            <span className="text-sm text-amber-600">Unsaved changes</span>
          )}
          <button
            onClick={save}
            disabled={saving || !hasChanges}
            className={`
              inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white
              ${saving || !hasChanges
                ? 'bg-gray-300 cursor-not-allowed'
                : 'bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500'
              }
            `}
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
      {successMessage && (
        <div className="rounded-md bg-green-50 p-4">
          <p className="text-sm text-green-800">{successMessage}</p>
        </div>
      )}

      {/* Tier Margins Table */}
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">Tier Margins</h3>
        <p className="text-sm text-gray-500 mb-4">
          Gross margin % applied to unit cost. Formula: selling price = cost / (1 - margin%)
        </p>
        <div className="overflow-hidden border border-gray-200 rounded-lg">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Tier
                </th>
                {DOOR_TYPES.map(dt => (
                  <th key={dt} className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                    {dt}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {TIER_ORDER.map(tier => {
                // Retail only shows for residential
                const showCommercial = tier !== 'retail'
                return (
                  <tr key={tier}>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-semibold capitalize ${TIER_COLORS[tier]}`}>
                        {tier}
                      </span>
                    </td>
                    {DOOR_TYPES.map(dt => (
                      <td key={dt} className="px-4 py-3 text-center">
                        {(dt === 'commercial' && !showCommercial) ? (
                          <span className="text-xs text-gray-400">N/A</span>
                        ) : (
                          <div className="inline-flex items-center">
                            <input
                              type="number"
                              min="0"
                              max="99"
                              step="1"
                              value={margins[dt]?.[tier] ?? ''}
                              onChange={e => handleMarginChange(dt, tier, e.target.value)}
                              className="w-16 text-center border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                            />
                            <span className="ml-1 text-sm text-gray-500">%</span>
                          </div>
                        )}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Cost Adjustments */}
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">Cost Adjustments</h3>
        <p className="text-sm text-gray-500 mb-4">
          Buffer % added to unit cost before margin calculation. Use when supplier cost increases are coming but BC isn't updated yet.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {categories.map(cat => {
            const entry = adjustments[cat.code] || { adjustment: 0, note: '' }
            return (
              <div key={cat.code} className="border border-gray-200 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span className="text-sm font-medium text-gray-900">{cat.label}</span>
                    <span className="ml-2 text-xs text-gray-400 font-mono">{cat.code}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2 mb-2">
                  <input
                    type="number"
                    min="-50"
                    max="100"
                    step="0.5"
                    value={entry.adjustment ?? 0}
                    onChange={e => handleAdjustmentChange(cat.code, 'adjustment', e.target.value)}
                    className={`w-20 text-center border rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500 ${
                      (entry.adjustment ?? 0) > 0
                        ? 'border-amber-300 bg-amber-50'
                        : (entry.adjustment ?? 0) < 0
                        ? 'border-blue-300 bg-blue-50'
                        : 'border-gray-300'
                    }`}
                  />
                  <span className="text-sm text-gray-500">%</span>
                </div>
                <input
                  type="text"
                  placeholder="Note (optional)"
                  value={entry.note || ''}
                  onChange={e => handleAdjustmentChange(cat.code, 'note', e.target.value)}
                  className="w-full text-xs border border-gray-200 rounded px-2 py-1 text-gray-600 focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                />
              </div>
            )
          })}
        </div>
      </div>

      {/* Formula Reference */}
      <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-600">
        <strong>Pricing Formula:</strong>{' '}
        <code className="bg-white px-1.5 py-0.5 rounded border text-xs font-mono">
          selling_price = (unitCost x (1 + adjustment%/100)) / (1 - margin%/100)
        </code>
        <p className="mt-2 text-xs text-gray-500">
          Example: unitCost $100, +5% cost adjustment, 30% margin = $100 x 1.05 / 0.70 = $150.00
        </p>
      </div>
    </div>
  )
}

export default PricingSettings
