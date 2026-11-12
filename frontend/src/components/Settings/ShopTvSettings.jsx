import { useEffect, useState } from 'react'
import { shopTvApi } from '../../api/client'

function listToText(values) {
  return (values || []).join(', ')
}

function textToList(value) {
  return value.split(/[\n,]+/).map((part) => part.trim()).filter(Boolean)
}

function formatWhen(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

function ShopTvSettings() {
  const [mode, setMode] = useState('off')
  const [pickups, setPickups] = useState('')
  const [deliveries, setDeliveries] = useState('')
  const [pickupAgents, setPickupAgents] = useState('')
  const [deliveryAgents, setDeliveryAgents] = useState('')
  const [agentMeansDelivery, setAgentMeansDelivery] = useState(false)
  const [outlook, setOutlook] = useState(false)
  const [mapping, setMapping] = useState([])
  const [tokens, setTokens] = useState([])
  const [name, setName] = useState('Shop TV')
  const [created, setCreated] = useState(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const apply = (data) => {
    setMode(data.mode === 'on' ? 'on' : 'off')
    setPickups(listToText(data.pickup_shipment_methods))
    setDeliveries(listToText(data.delivery_shipment_methods))
    setPickupAgents(listToText(data.pickup_shipping_agents))
    setDeliveryAgents(listToText(data.delivery_shipping_agents))
    setAgentMeansDelivery(Boolean(data.shipping_agent_means_delivery))
    setOutlook(Boolean(data.outlook_calendar_enabled))
    setMapping(data.mapping || [])
    setTokens(data.tokens || [])
  }

  const load = async () => {
    setError('')
    try {
      const response = await shopTvApi.settings()
      apply(response.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load the shop TV settings')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const save = async () => {
    setBusy(true)
    setSaved('')
    setError('')
    try {
      await shopTvApi.saveSettings({
        mode,
        pickup_shipment_methods: textToList(pickups),
        delivery_shipment_methods: textToList(deliveries),
        pickup_shipping_agents: textToList(pickupAgents),
        delivery_shipping_agents: textToList(deliveryAgents),
        shipping_agent_means_delivery: agentMeansDelivery,
      })
      setSaved(mode === 'on' ? 'Shop TV is on.' : 'Shop TV is off. The board route is hidden.')
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save')
    } finally {
      setBusy(false)
    }
  }

  const createLink = async () => {
    setBusy(true)
    setError('')
    setCreated(null)
    try {
      const response = await shopTvApi.createKiosk({ name: name.trim() || 'Shop TV' })
      const path = response.data.path
      setCreated({
        path,
        url: `${window.location.origin}${path}`,
      })
      setName('Shop TV')
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create a shop link')
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (id) => {
    setBusy(true)
    setError('')
    try {
      await shopTvApi.revokeKiosk(id)
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not revoke that link')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <p className="text-sm text-gray-500">Loading shop TV settings…</p>
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Shop TV board</h2>
        <p className="mt-1 text-sm text-gray-600">
          Cast <span className="font-medium">/shop-tv</span> from a Chrome tab. The link below is read-only.
          It can only load this board, and revoking it stops the TV on the next refresh. It is not a staff login.
        </p>
      </div>

      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {saved && <p className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">{saved}</p>}

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-gray-700">Board</span>
        {['off', 'on'].map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setMode(value)}
            className={`rounded-md px-4 py-2 text-sm font-semibold ${
              mode === value ? 'bg-odc-800 text-white' : 'bg-gray-100 text-gray-700'
            }`}
          >
            {value === 'on' ? 'On' : 'Off'}
          </button>
        ))}
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="rounded-md bg-odc-600 px-4 py-2 text-sm font-semibold text-white hover:bg-odc-700 disabled:opacity-50"
        >
          Save
        </button>
      </div>
      <p className="text-sm text-gray-500">
        Off returns 404 for the board and hides Shop TV in the menu. Default is off.
      </p>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="block text-sm">
          <span className="font-medium text-gray-700">Pickup shipment methods</span>
          <textarea
            value={pickups}
            onChange={(event) => setPickups(event.target.value)}
            rows={3}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-gray-700">Delivery shipment methods</span>
          <textarea
            value={deliveries}
            onChange={(event) => setDeliveries(event.target.value)}
            rows={3}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-gray-700">Pickup shipping agents</span>
          <input
            value={pickupAgents}
            onChange={(event) => setPickupAgents(event.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-gray-700">Delivery shipping agents</span>
          <input
            value={deliveryAgents}
            onChange={(event) => setDeliveryAgents(event.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
      </div>
      <label className="flex items-start gap-2 text-sm text-gray-700">
        <input
          type="checkbox"
          checked={agentMeansDelivery}
          onChange={(event) => setAgentMeansDelivery(event.target.checked)}
          className="mt-1"
        />
        <span>Treat any shipping agent that is not listed as a pickup as a delivery. Leave this off until the agent codes are confirmed.</span>
      </label>

      <details className="rounded-md border border-gray-200 px-4 py-3 text-sm text-gray-700">
        <summary className="cursor-pointer font-medium text-gray-900">How an order lands on a lane</summary>
        <ul className="mt-3 list-disc space-y-2 pl-5">
          {mapping.map((note) => <li key={note}>{note}</li>)}
        </ul>
        {outlook && <p className="mt-3">Outlook calendar reading is marked on, and the stub still returns no events.</p>}
      </details>

      <div className="border-t border-gray-200 pt-6">
        <h3 className="text-base font-semibold text-gray-900">Shop TV link</h3>
        <p className="mt-1 text-sm text-gray-600">
          Open the link in Chrome and cast the tab. The secret is shown once. Revoke it here to turn that screen off.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="block text-sm">
            <span className="font-medium text-gray-700">Name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="mt-1 block w-64 rounded-md border border-gray-300 px-3 py-2"
            />
          </label>
          <button
            type="button"
            onClick={createLink}
            disabled={busy}
            className="rounded-md bg-odc-600 px-4 py-2 text-sm font-semibold text-white hover:bg-odc-700 disabled:opacity-50"
          >
            Create link
          </button>
        </div>
        {created && (
          <div className="mt-4 rounded-md border border-amber-300 bg-amber-50 p-4">
            <p className="text-sm font-semibold text-amber-900">Copy this now. It will not be shown again.</p>
            <input readOnly value={created.url} className="mt-2 w-full rounded-md border border-amber-200 bg-white px-3 py-2 font-mono text-sm" />
          </div>
        )}
        <ul className="mt-4 divide-y divide-gray-100">
          {tokens.length === 0 && <li className="py-3 text-sm text-gray-500">No shop TV links yet.</li>}
          {tokens.map((token) => (
            <li key={token.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
              <div>
                <p className="font-medium text-gray-900">{token.name}</p>
                <p className="text-gray-500">
                  {token.prefix}… · {token.status} · last used {formatWhen(token.last_used_at)}
                </p>
              </div>
              {token.status !== 'revoked' && (
                <button
                  type="button"
                  onClick={() => revoke(token.id)}
                  disabled={busy}
                  className="rounded-md border border-red-300 px-3 py-1.5 font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                >
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export default ShopTvSettings
