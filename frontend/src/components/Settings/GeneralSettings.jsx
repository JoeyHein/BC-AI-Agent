import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { customersApi, freightEstimatorApi } from '../../api/client'

const INBOX_SWITCHES = [
  ['email_attachment_reading', 'Read email attachments', 'PDFs that already have text, and DXF drawings, are read for door sizes. A scanned page or a picture is listed and not read. Shadow logs the openings and does not change the quote.'],
  ['missing_info_reply', 'Missing-info reply', 'Draft one reply listing what is still unknown. It waits in the approval queue.'],
  ['quote_send_draft', 'Send-quote draft', 'When a quote is created from an email, draft a reply with the SQ PDF. It is not sent.'],
  ['customer_approval_detection', 'Customer approval', 'A go-ahead email queues a convert-to-sales-order for staff. Nothing converts on its own.'],
]

const QUOTE_BUILD_SWITCHES = [
  ['quote_window_patterns', 'Window patterns', 'Turn "3 windows in section 1" or a staggered pattern into glass kits on those sections.'],
  ['quote_opener_mapping', 'Opener and keypad mapping', 'Map LiftMaster wording to a catalog part. An unsure name is flagged and not priced at $0.'],
  ['quote_struts_per_section', 'Struts on every section', 'When the email or the profile asks for a truss on every section, quote one per section.'],
  ['quote_crating_history', 'Crating, pickup, and freight', 'Add crating when the email asks or the customer usually takes it, and record pickup versus delivery.'],
  ['quote_kanata_series_history', 'Kanata series history', 'Count Kanata PN65 panels when learning which series a customer orders.'],
  ['quote_adjustable_prep', 'Adjustable prep', 'Record adjustable or opener prep when the email asks. No part is invented when the catalog has none.'],
  ['quote_series_fallback', 'Closest series', 'When the asked series cannot be built in that colour and design, quote the closest series that can.'],
]

function PriceOverrideControl({ label, help, mode, onMode, modes = ['off', 'shadow', 'on'], children }) {
  return (
    <div className="text-sm text-gray-700">
      <span className="block text-xs font-medium text-gray-500 mb-1">{label}</span>
      <span className="block text-xs text-gray-500 mb-1">{help}</span>
      <select
        aria-label={label}
        value={mode || 'off'}
        onChange={onMode}
        className="border border-gray-300 rounded-md px-2 py-1 text-sm"
      >
        {modes.map((value) => (
          <option key={value} value={value}>{value === 'off' ? 'Off' : value === 'shadow' ? 'Shadow' : 'On'}</option>
        ))}
      </select>
      {children}
    </div>
  )
}

function GeneralSettings() {
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ['profile-quoting-mode'],
    queryFn: async () => (await customersApi.getProfileQuotingMode()).data,
  })
  const inbox = useQuery({
    queryKey: ['inbox-automation'],
    queryFn: async () => (await customersApi.getInboxModes()).data,
  })
  const shopDrawings = useQuery({
    queryKey: ['shop-drawing-flags'],
    queryFn: async () => (await customersApi.getShopDrawingFlags()).data,
  })
  const prices = useQuery({
    queryKey: ['quote-price-overrides'],
    queryFn: async () => (await customersApi.getQuotePriceOverrides()).data,
  })
  const freight = useQuery({
    queryKey: ['freight-estimator-settings'],
    queryFn: async () => (await freightEstimatorApi.settings()).data,
  })
  const mode = data?.mode || 'off'
  const inboxModes = inbox.data?.modes || {}
  const shopModes = shopDrawings.data?.modes || {}
  const panelSetting = prices.data?.quote_replacement_section_pricing || {}
  const finderSetting = prices.data?.quote_section_finder || {}
  const windowSetting = prices.data?.quote_flat_residential_windows || {}

  async function changeMode(next) {
    const labels = {
      off: 'Turn customer-profile quoting off? Live quotes go back to the previous defaults immediately.',
      shadow: 'Turn on shadow mode? The profile is calculated and saved, and the Business Central quote stays unchanged.',
      on: 'Turn customer-profile quoting on? Silent emails will use customer profiles, and unmatched senders will be held.',
    }
    if (!window.confirm(labels[next])) return
    await customersApi.setProfileQuotingMode(next)
    queryClient.invalidateQueries({ queryKey: ['profile-quoting-mode'] })
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-medium text-gray-900">General Settings</h2>
        <p className="text-sm text-gray-500">
          Configure general application preferences
        </p>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h3 className="text-sm font-medium text-gray-900">Customer profile quoting</h3>
        <p className="mt-1 text-sm text-gray-600">
          Company-wide. Off is the production default. Shadow records what a profile would have changed without sending that quote to Business Central.
        </p>
        <label className="mt-3 block text-sm text-gray-700">
          <span className="block text-xs font-medium text-gray-500 mb-1">Mode</span>
          <select
            aria-label="Customer profile quoting mode"
            value={mode}
            onChange={(event) => changeMode(event.target.value)}
            className="border border-gray-300 rounded-md px-2 py-1 text-sm"
          >
            <option value="off">Off</option>
            <option value="shadow">Shadow</option>
            <option value="on">On</option>
          </select>
        </label>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-5">
        <div>
          <h3 className="text-sm font-medium text-gray-900">Shop drawings</h3>
          <p className="mt-1 text-sm text-gray-600">
            Off keeps the current schematic. On draws the Upwardor tongue-and-groove profile and the wood or steel jamb sideroom.
          </p>
        </div>
        <label className="block text-sm text-gray-700">
          <span className="block text-xs font-medium text-gray-500 mb-1">Real panel profiles</span>
          <span className="block text-xs text-gray-500 mb-1">
            TX thickness follows the series number in millimetres. Wood jambs use 3.75 inch sideroom. Steel jamb welds stay at 3.5 inch.
          </span>
          <select
            aria-label="Real panel profiles"
            value={shopModes.shop_drawing_real_profiles || 'off'}
            onChange={async (event) => {
              const next = event.target.value
              if (!window.confirm(`Set Real panel profiles to ${next}?`)) return
              await customersApi.setShopDrawingFlags({ shop_drawing_real_profiles: next })
              queryClient.invalidateQueries({ queryKey: ['shop-drawing-flags'] })
            }}
            className="border border-gray-300 rounded-md px-2 py-1 text-sm"
          >
            <option value="off">Off</option>
            <option value="on">On</option>
          </select>
        </label>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-5">
        <div>
          <h3 className="text-sm font-medium text-gray-900">Quote inbox</h3>
          <p className="mt-1 text-sm text-gray-600">
            Each one is off until you turn it on. Shadow writes down what it would do and does not create a draft or a quote. Mail still leaves only after someone approves it.
          </p>
        </div>
        {INBOX_SWITCHES.map(([key, label, help]) => (
          <label key={key} className="block text-sm text-gray-700">
            <span className="block text-xs font-medium text-gray-500 mb-1">{label}</span>
            <span className="block text-xs text-gray-500 mb-1">{help}</span>
            <select
              aria-label={label}
              value={inboxModes[key] || 'off'}
              onChange={async (event) => {
                const next = event.target.value
                if (!window.confirm(`Set ${label} to ${next}?`)) return
                await customersApi.setInboxModes({ [key]: next })
                queryClient.invalidateQueries({ queryKey: ['inbox-automation'] })
              }}
              className="border border-gray-300 rounded-md px-2 py-1 text-sm"
            >
              <option value="off">Off</option>
              <option value="shadow">Shadow</option>
              <option value="on">On</option>
            </select>
          </label>
        ))}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-5">
        <div>
          <h3 className="text-sm font-medium text-gray-900">Quote build</h3>
          <p className="mt-1 text-sm text-gray-600">
            Each one is off until you turn it on. Shadow writes down the parts it would add and leaves the quote unchanged. 3 inch track is always a 15 inch radius, and that is not one of these switches.
          </p>
        </div>
        {QUOTE_BUILD_SWITCHES.map(([key, label, help]) => (
          <label key={key} className="block text-sm text-gray-700">
            <span className="block text-xs font-medium text-gray-500 mb-1">{label}</span>
            <span className="block text-xs text-gray-500 mb-1">{help}</span>
            <select
              aria-label={label}
              value={inboxModes[key] || 'off'}
              onChange={async (event) => {
                const next = event.target.value
                if (!window.confirm(`Set ${label} to ${next}?`)) return
                await customersApi.setInboxModes({ [key]: next })
                queryClient.invalidateQueries({ queryKey: ['inbox-automation'] })
              }}
              className="border border-gray-300 rounded-md px-2 py-1 text-sm"
            >
              <option value="off">Off</option>
              <option value="shadow">Shadow</option>
              <option value="on">On</option>
            </select>
          </label>
        ))}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-5">
        <div>
          <h3 className="text-sm font-medium text-gray-900">Quote pricing</h3>
          <p className="mt-1 text-sm text-gray-600">
            Both are off until you turn them on. Shadow writes the price it would use and leaves the quote on the price list.
          </p>
        </div>
        <PriceOverrideControl
          label="Replacement section list price"
          help="Panels-only and door-face orders sell each steel section at the item-card list price. A complete door keeps the customer's price list. A missing list price is flagged and left as Business Central priced it."
          mode={panelSetting.mode}
          onMode={async (event) => {
            const next = event.target.value
            if (!window.confirm(`Set Replacement section list price to ${next}?`)) return
            await customersApi.setQuotePriceOverrides({ quote_replacement_section_pricing: next })
            queryClient.invalidateQueries({ queryKey: ['quote-price-overrides'] })
          }}
        />
        <PriceOverrideControl
          label="Replacement section finder"
          help="Customers can describe a replacement section in the portal. Off hides the page. On lets them add a resolved section to the cart, or send an unresolved one to staff. This switch has no shadow mode."
          mode={finderSetting.mode === 'on' ? 'on' : 'off'}
          modes={['off', 'on']}
          onMode={async (event) => {
            const next = event.target.value
            if (!window.confirm(`Set Replacement section finder to ${next}?`)) return
            await customersApi.setQuotePriceOverrides({ quote_section_finder: next })
            queryClient.invalidateQueries({ queryKey: ['quote-price-overrides'] })
          }}
        />
        <PriceOverrideControl
          label="Flat residential windows"
          help="Residential doors price each glass kit at one rate per window. A decorative insert on that door is included at $0. Commercial doors, including TX450 and TX500, stay on the price list."
          mode={windowSetting.mode}
          onMode={async (event) => {
            const next = event.target.value
            if (!window.confirm(`Set Flat residential windows to ${next}?`)) return
            await customersApi.setQuotePriceOverrides({ quote_flat_residential_windows: next })
            queryClient.invalidateQueries({ queryKey: ['quote-price-overrides'] })
          }}
        >
          <div className="mt-2 flex gap-3">
            <label className="block text-xs text-gray-500">
              Long window, each (CAD)
              <input
                aria-label="Long window price"
                type="number"
                min="0.01"
                step="0.01"
                defaultValue={windowSetting.long_price ?? 165}
                key={`long-${windowSetting.long_price ?? 165}`}
                onBlur={async (event) => {
                  const next = event.target.value
                  if (String(next) === String(windowSetting.long_price ?? 165)) return
                  if (!window.confirm(`Set the long window price to $${next}?`)) {
                    event.target.value = windowSetting.long_price ?? 165
                    return
                  }
                  await customersApi.setQuotePriceOverrides({ residential_window_long_price: Number(next) })
                  queryClient.invalidateQueries({ queryKey: ['quote-price-overrides'] })
                }}
                className="mt-1 block w-28 border border-gray-300 rounded-md px-2 py-1 text-sm text-gray-900"
              />
            </label>
            <label className="block text-xs text-gray-500">
              Short window, each (CAD)
              <input
                aria-label="Short window price"
                type="number"
                min="0.01"
                step="0.01"
                defaultValue={windowSetting.short_price ?? 120}
                key={`short-${windowSetting.short_price ?? 120}`}
                onBlur={async (event) => {
                  const next = event.target.value
                  if (String(next) === String(windowSetting.short_price ?? 120)) return
                  if (!window.confirm(`Set the short window price to $${next}?`)) {
                    event.target.value = windowSetting.short_price ?? 120
                    return
                  }
                  await customersApi.setQuotePriceOverrides({ residential_window_short_price: Number(next) })
                  queryClient.invalidateQueries({ queryKey: ['quote-price-overrides'] })
                }}
                className="mt-1 block w-28 border border-gray-300 rounded-md px-2 py-1 text-sm text-gray-900"
              />
            </label>
          </div>
        </PriceOverrideControl>
      </div>

      <FreightEstimatorSettings
        settings={freight.data}
        onSaved={() => queryClient.invalidateQueries({ queryKey: ['freight-estimator-settings'] })}
      />

      {/* Placeholder content */}
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
        <svg
          className="mx-auto h-12 w-12 text-gray-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1}
            d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"
          />
        </svg>
        <h3 className="mt-4 text-sm font-medium text-gray-900">Coming Soon</h3>
        <p className="mt-2 text-sm text-gray-500">
          General settings such as company information, default values, and preferences
          will be available here in a future update.
        </p>
      </div>

      {/* Future settings preview */}
      <div className="border-t border-gray-200 pt-6">
        <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-4">
          Planned Settings
        </h3>
        <ul className="space-y-3">
          <li className="flex items-center text-sm text-gray-600">
            <span className="w-2 h-2 bg-gray-300 rounded-full mr-3"></span>
            Company Information
          </li>
          <li className="flex items-center text-sm text-gray-600">
            <span className="w-2 h-2 bg-gray-300 rounded-full mr-3"></span>
            Default Track Sizes
          </li>
          <li className="flex items-center text-sm text-gray-600">
            <span className="w-2 h-2 bg-gray-300 rounded-full mr-3"></span>
            Hardware Preferences
          </li>
          <li className="flex items-center text-sm text-gray-600">
            <span className="w-2 h-2 bg-gray-300 rounded-full mr-3"></span>
            Pricing Rules & Markup
          </li>
          <li className="flex items-center text-sm text-gray-600">
            <span className="w-2 h-2 bg-gray-300 rounded-full mr-3"></span>
            User Management (Admin)
          </li>
        </ul>
      </div>
    </div>
  )
}

function FreightEstimatorSettings({ settings, onSaved }) {
  const [form, setForm] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!settings) return
    const config = settings.config || {}
    const crate = { ...(settings.crate_defaults || {}), ...(config.crate || {}) }
    const operators = {}
    Object.entries(settings.operators || {}).forEach(([key, row]) => {
      operators[key] = row.lb
    })
    setForm({
      mode: settings.mode || 'off',
      fuel_percent: config.fuel_percent ?? 68.8,
      long_charge: config.long_charge ?? 75,
      long_min_length_in: config.long_min_length_in ?? 96,
      density_lb_per_cuft: config.density_lb_per_cuft ?? 10,
      gst_percent: config.gst_percent ?? 5,
      crate: {
        shaft_overhang_in: crate.shaft_overhang_in,
        dunnage_in: crate.dunnage_in,
        packing_allowance_in: crate.packing_allowance_in,
        max_stack_height_in: crate.max_stack_height_in,
        tare_base_lb: crate.tare_base_lb,
        tare_lb_per_ft: crate.tare_lb_per_ft,
      },
      operator_lb: operators,
      shaft_lb_per_ft: { ...(settings.shaft_lb_per_ft || {}), ...(config.shaft_lb_per_ft || {}) },
    })
  }, [settings])

  if (!form) return null

  function setCrate(key, value) {
    setForm((current) => ({ ...current, crate: { ...current.crate, [key]: value } }))
  }

  async function save(event) {
    event.preventDefault()
    if (!window.confirm('Save the freight estimator settings?')) return
    setMessage('')
    const number = (value) => Number(value)
    await freightEstimatorApi.saveSettings({
      mode: form.mode,
      fuel_percent: number(form.fuel_percent),
      long_charge: number(form.long_charge),
      long_min_length_in: number(form.long_min_length_in),
      density_lb_per_cuft: number(form.density_lb_per_cuft),
      gst_percent: number(form.gst_percent),
      crate: Object.fromEntries(Object.entries(form.crate).map(([key, value]) => [key, number(value)])),
      operator_lb: Object.fromEntries(Object.entries(form.operator_lb).map(([key, value]) => [key, number(value)])),
      shaft_lb_per_ft: Object.fromEntries(Object.entries(form.shaft_lb_per_ft).map(([key, value]) => [key, number(value)])),
    })
    setMessage('Saved.')
    onSaved()
  }

  const crateFields = [
    ['shaft_overhang_in', 'Shaft overhang, in'],
    ['dunnage_in', 'Dunnage, in'],
    ['packing_allowance_in', 'Packing allowance, in'],
    ['max_stack_height_in', 'Max stack, in'],
    ['tare_base_lb', 'Crate tare base, lb'],
    ['tare_lb_per_ft', 'Crate tare, lb/ft'],
  ]

  return (
    <form onSubmit={save} className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
      <div>
        <h3 className="text-sm font-medium text-gray-900">Freight estimator</h3>
        <p className="mt-1 text-sm text-gray-600">
          Off hides the freight panel and the business page. On estimates ship weight and a Manitoulin contract rate. It does not write to Business Central. Agreement #19067426 must be signed before the rate is used. LONG is charged on each long piece. Whether Manitoulin bills FLT once per shipment is still unconfirmed.
        </p>
      </div>
      <label className="block text-sm text-gray-700">
        <span className="block text-xs font-medium text-gray-500 mb-1">Freight estimator</span>
        <select aria-label="Freight estimator" value={form.mode} onChange={(event) => setForm({ ...form, mode: event.target.value })} className="border border-gray-300 rounded-md px-2 py-1 text-sm">
          <option value="off">Off</option>
          <option value="on">On</option>
        </select>
      </label>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <NumberField label="Fuel % on linehaul" value={form.fuel_percent} onChange={(value) => setForm({ ...form, fuel_percent: value })} />
        <NumberField label="LONG charge, CAD" value={form.long_charge} onChange={(value) => setForm({ ...form, long_charge: value })} />
        <NumberField label="LONG from length, in" value={form.long_min_length_in} onChange={(value) => setForm({ ...form, long_min_length_in: value })} />
        <NumberField label="Density, lb/cu ft" value={form.density_lb_per_cuft} onChange={(value) => setForm({ ...form, density_lb_per_cuft: value })} />
        <NumberField label="GST %" value={form.gst_percent} onChange={(value) => setForm({ ...form, gst_percent: value })} />
        <NumberField label="1 in solid shaft, lb/ft" value={form.shaft_lb_per_ft.solid ?? ''} onChange={(value) => setForm({ ...form, shaft_lb_per_ft: { ...form.shaft_lb_per_ft, solid: value } })} />
        <NumberField label="1 in tube shaft, lb/ft" value={form.shaft_lb_per_ft.tube ?? ''} onChange={(value) => setForm({ ...form, shaft_lb_per_ft: { ...form.shaft_lb_per_ft, tube: value } })} />
        {crateFields.map(([key, label]) => (
          <NumberField key={key} label={label} value={form.crate[key]} onChange={(value) => setCrate(key, value)} />
        ))}
        {Object.entries(settings?.operators || {}).map(([key, row]) => (
          <NumberField key={key} label={`${row.label}, lb`} value={form.operator_lb[key]} onChange={(value) => setForm({ ...form, operator_lb: { ...form.operator_lb, [key]: value } })} />
        ))}
      </div>
      <button type="submit" className="inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700">
        Save freight settings
      </button>
      {message && <p className="text-sm text-gray-600">{message}</p>}
    </form>
  )
}

function NumberField({ label, value, onChange }) {
  return (
    <label className="block text-xs text-gray-500">
      {label}
      <input
        aria-label={label}
        type="number"
        step="0.01"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 block w-full border border-gray-300 rounded-md px-2 py-1 text-sm text-gray-900"
      />
    </label>
  )
}

export default GeneralSettings
