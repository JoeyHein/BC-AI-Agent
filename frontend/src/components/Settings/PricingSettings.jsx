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

const TIER_OPTIONS = [
  { value: '', label: '— Unmapped —' },
  { value: 'gold', label: 'Gold' },
  { value: 'silver', label: 'Silver' },
  { value: 'bronze', label: 'Bronze' },
  { value: 'retail', label: 'Retail' },
]

function PricingSettings() {
  const [margins, setMargins] = useState({})
  const [adjustments, setAdjustments] = useState({})
  const [categories, setCategories] = useState([])
  const [prefixMargins, setPrefixMargins] = useState({})  // { "GK17": { margin: 60, note: "..." } }
  const [newPrefix, setNewPrefix] = useState('')
  const [newPrefixMargin, setNewPrefixMargin] = useState('')
  const [newPrefixNote, setNewPrefixNote] = useState('')
  const [groupMapping, setGroupMapping] = useState({})   // { "CONTRACTOR": "gold", ... }
  const [bcGroups, setBcGroups] = useState([])           // groups seen in synced customers
  const [newGroupCode, setNewGroupCode] = useState('')   // manual entry for unknown groups
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

      const [tiersRes, adjRes, catRes, mappingRes, groupsRes, prefixRes] = await Promise.all([
        settingsApi.getPricingTiers(),
        settingsApi.getPricingCostAdjustments(),
        settingsApi.getPricingCategories(),
        settingsApi.getBCGroupMapping(),
        settingsApi.getBCPriceGroups(),
        settingsApi.getPrefixMargins(),
      ])

      if (tiersRes.data.success) setMargins(tiersRes.data.data.margins)
      if (adjRes.data.success) setAdjustments(adjRes.data.data.adjustments)
      if (catRes.data.success) setCategories(catRes.data.data)
      if (mappingRes.data.success) setGroupMapping(mappingRes.data.data.mapping || {})
      if (groupsRes.data.success) setBcGroups(groupsRes.data.data || [])
      if (prefixRes.data.success) setPrefixMargins(prefixRes.data.data.overrides || {})
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
      [doorType]: { ...prev[doorType], [tier]: num }
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

  const handleGroupMappingChange = (groupCode, tier) => {
    setGroupMapping(prev => {
      const next = { ...prev }
      if (!tier) {
        delete next[groupCode]
      } else {
        next[groupCode] = tier
      }
      return next
    })
    setHasChanges(true)
    setSuccessMessage(null)
  }

  const addGroupCode = () => {
    const code = newGroupCode.trim().toUpperCase()
    if (!code) return
    if (!bcGroups.includes(code)) {
      setBcGroups(prev => [...prev, code].sort())
    }
    setNewGroupCode('')
  }

  const removeGroupCode = (code) => {
    setBcGroups(prev => prev.filter(g => g !== code))
    setGroupMapping(prev => {
      const next = { ...prev }
      delete next[code]
      return next
    })
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

      // Validate prefix margins
      for (const [prefix, entry] of Object.entries(prefixMargins)) {
        const m = entry?.margin
        if (m === '' || m === undefined || m < 0 || m > 99) {
          setError(`Prefix margin for ${prefix} must be 0-99%`)
          return
        }
      }

      await Promise.all([
        settingsApi.updatePricingTiers(margins),
        settingsApi.updatePricingCostAdjustments(adjustments),
        settingsApi.updateBCGroupMapping(groupMapping),
        settingsApi.updatePrefixMargins(prefixMargins),
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

  // All BC group codes to show: union of synced groups + any in the current mapping
  const allGroups = [...new Set([...bcGroups, ...Object.keys(groupMapping)])].sort()

  return (
    <div className="space-y-8">
      {/* Header with Save Button */}
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Pricing & Margins</h2>
          <p className="mt-1 text-sm text-gray-500">
            Configure margin tiers, cost adjustments, and BC price group mappings.
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

      {/* BC Price Group → Tier Mapping */}
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">BC Price Group → Portal Tier</h3>
        <p className="text-sm text-gray-500 mb-4">
          Map each Business Central customer price group code to a portal pricing tier.
          When customers sync from BC, their tier is automatically set based on this mapping.
          Manually-set tiers are preserved when no mapping exists for a group.
        </p>

        <div className="overflow-hidden border border-gray-200 rounded-lg">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/3">
                  BC Price Group Code
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/3">
                  Portal Tier
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/4">
                  Preview
                </th>
                <th className="px-4 py-3 w-12" />
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {allGroups.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-sm text-gray-400">
                    No BC price groups found. Sync customers from BC or add groups manually below.
                  </td>
                </tr>
              ) : (
                allGroups.map(code => {
                  const currentTier = groupMapping[code] || ''
                  const fromSync = bcGroups.includes(code)
                  return (
                    <tr key={code}>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm text-gray-900">{code}</span>
                          {fromSync && (
                            <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">from BC</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <select
                          value={currentTier}
                          onChange={e => handleGroupMappingChange(code, e.target.value)}
                          className="block w-full border border-gray-300 rounded-md shadow-sm py-1.5 px-3 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                        >
                          {TIER_OPTIONS.map(opt => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-3">
                        {currentTier ? (
                          <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-semibold capitalize ${TIER_COLORS[currentTier]}`}>
                            {currentTier}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400 italic">Unmapped</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {!fromSync && (
                          <button
                            onClick={() => removeGroupCode(code)}
                            className="text-red-400 hover:text-red-600 text-xs"
                            title="Remove"
                          >
                            ✕
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Manual group code entry */}
        <div className="mt-3 flex items-center gap-2">
          <input
            type="text"
            placeholder="Add BC group code (e.g. CONTRACTOR)"
            value={newGroupCode}
            onChange={e => setNewGroupCode(e.target.value.toUpperCase())}
            onKeyDown={e => e.key === 'Enter' && addGroupCode()}
            className="block w-56 border border-gray-300 rounded-md shadow-sm py-1.5 px-3 text-sm font-mono focus:outline-none focus:ring-odc-500 focus:border-odc-500"
          />
          <button
            onClick={addGroupCode}
            disabled={!newGroupCode.trim()}
            className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-40"
          >
            + Add
          </button>
          <span className="text-xs text-gray-400">
            Add a group code that isn't yet seen in synced customers.
          </span>
        </div>
      </div>

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

      {/* Part Prefix Margin Overrides */}
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">Part Prefix Margin Overrides</h3>
        <p className="text-sm text-gray-500 mb-4">
          Override the tier margin for parts whose number starts with a specific prefix.
          For example, GK17 (aluminum glazing) can be set to 60% regardless of customer tier.
        </p>
        <div className="overflow-hidden border border-gray-200 rounded-lg">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/4">
                  Part Prefix
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider w-1/6">
                  Margin %
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Note
                </th>
                <th className="px-4 py-3 w-12" />
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {Object.keys(prefixMargins).length === 0 && !newPrefix ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-sm text-gray-400">
                    No prefix overrides configured. Add one below.
                  </td>
                </tr>
              ) : (
                Object.entries(prefixMargins)
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([prefix, entry]) => (
                    <tr key={prefix}>
                      <td className="px-4 py-3">
                        <span className="font-mono text-sm text-gray-900">{prefix}</span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <div className="inline-flex items-center">
                          <input
                            type="number"
                            min="0"
                            max="99"
                            step="1"
                            value={entry.margin ?? ''}
                            onChange={e => {
                              const val = e.target.value === '' ? '' : parseFloat(e.target.value)
                              setPrefixMargins(prev => ({
                                ...prev,
                                [prefix]: { ...prev[prefix], margin: val }
                              }))
                              setHasChanges(true)
                              setSuccessMessage(null)
                            }}
                            className="w-16 text-center border border-gray-300 rounded-md shadow-sm py-1 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                          />
                          <span className="ml-1 text-sm text-gray-500">%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <input
                          type="text"
                          value={entry.note || ''}
                          onChange={e => {
                            setPrefixMargins(prev => ({
                              ...prev,
                              [prefix]: { ...prev[prefix], note: e.target.value }
                            }))
                            setHasChanges(true)
                            setSuccessMessage(null)
                          }}
                          placeholder="Optional note"
                          className="w-full text-sm border border-gray-200 rounded px-2 py-1 text-gray-600 focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                        />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => {
                            setPrefixMargins(prev => {
                              const next = { ...prev }
                              delete next[prefix]
                              return next
                            })
                            setHasChanges(true)
                            setSuccessMessage(null)
                          }}
                          className="text-red-400 hover:text-red-600 text-xs"
                          title="Remove override"
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))
              )}
            </tbody>
          </table>
        </div>

        {/* Add new prefix override */}
        <div className="mt-3 flex items-center gap-2">
          <input
            type="text"
            placeholder="Prefix (e.g. GK17)"
            value={newPrefix}
            onChange={e => setNewPrefix(e.target.value.toUpperCase())}
            className="block w-28 border border-gray-300 rounded-md shadow-sm py-1.5 px-3 text-sm font-mono focus:outline-none focus:ring-odc-500 focus:border-odc-500"
          />
          <div className="inline-flex items-center">
            <input
              type="number"
              min="0"
              max="99"
              step="1"
              placeholder="60"
              value={newPrefixMargin}
              onChange={e => setNewPrefixMargin(e.target.value)}
              className="w-16 text-center border border-gray-300 rounded-md shadow-sm py-1.5 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
            />
            <span className="ml-1 text-sm text-gray-500">%</span>
          </div>
          <input
            type="text"
            placeholder="Note (optional)"
            value={newPrefixNote}
            onChange={e => setNewPrefixNote(e.target.value)}
            className="block w-48 border border-gray-300 rounded-md shadow-sm py-1.5 px-3 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
          />
          <button
            onClick={() => {
              const prefix = newPrefix.trim().toUpperCase()
              const margin = parseFloat(newPrefixMargin)
              if (!prefix || isNaN(margin) || margin < 0 || margin > 99) return
              setPrefixMargins(prev => ({
                ...prev,
                [prefix]: { margin, note: newPrefixNote.trim() }
              }))
              setNewPrefix('')
              setNewPrefixMargin('')
              setNewPrefixNote('')
              setHasChanges(true)
              setSuccessMessage(null)
            }}
            disabled={!newPrefix.trim() || !newPrefixMargin}
            className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-40"
          >
            + Add
          </button>
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
          selling_price = (unitCost × (1 + adjustment%/100)) / (1 - margin%/100)
        </code>
        <p className="mt-2 text-xs text-gray-500">
          Example: unitCost $100, +5% cost adjustment, 30% margin = $100 × 1.05 / 0.70 = $150.00
        </p>
      </div>
    </div>
  )
}

export default PricingSettings
