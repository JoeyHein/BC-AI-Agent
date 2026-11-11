import { useQuery, useQueryClient } from '@tanstack/react-query'
import { customersApi } from '../../api/client'

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

function PriceOverrideControl({ label, help, mode, onMode, children }) {
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
        <option value="off">Off</option>
        <option value="shadow">Shadow</option>
        <option value="on">On</option>
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
  const prices = useQuery({
    queryKey: ['quote-price-overrides'],
    queryFn: async () => (await customersApi.getQuotePriceOverrides()).data,
  })
  const mode = data?.mode || 'off'
  const inboxModes = inbox.data?.modes || {}
  const panelSetting = prices.data?.quote_replacement_panel_margin || {}
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
          label="Replacement section margin"
          help="Panels-only and door-face orders price each steel section at unit cost divided by (1 minus this margin). A complete door is unchanged. 50 percent is cost times 2."
          mode={panelSetting.mode}
          onMode={async (event) => {
            const next = event.target.value
            if (!window.confirm(`Set Replacement section margin to ${next}?`)) return
            await customersApi.setQuotePriceOverrides({ quote_replacement_panel_margin: next })
            queryClient.invalidateQueries({ queryKey: ['quote-price-overrides'] })
          }}
        >
          <label className="block mt-2 text-xs text-gray-500">
            Gross margin percent
            <input
              aria-label="Replacement section margin percent"
              type="number"
              min="0"
              max="99"
              step="1"
              defaultValue={panelSetting.margin_percent ?? 50}
              key={panelSetting.margin_percent ?? 50}
              onBlur={async (event) => {
                const next = event.target.value
                if (String(next) === String(panelSetting.margin_percent ?? 50)) return
                if (!window.confirm(`Set the replacement section margin to ${next} percent?`)) {
                  event.target.value = panelSetting.margin_percent ?? 50
                  return
                }
                await customersApi.setQuotePriceOverrides({ replacement_margin_percent: Number(next) })
                queryClient.invalidateQueries({ queryKey: ['quote-price-overrides'] })
              }}
              className="mt-1 block w-28 border border-gray-300 rounded-md px-2 py-1 text-sm text-gray-900"
            />
          </label>
        </PriceOverrideControl>
        <PriceOverrideControl
          label="Flat residential windows"
          help="Kanata, Craft, TX450, and TX500 residential glass kits and inserts use one price per window. Commercial GK16 and aluminum windows stay on the price list."
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

export default GeneralSettings
