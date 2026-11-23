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

const ENTRY_LANES = [
  { id: 'pickup', label: 'Pickup' },
  { id: 'delivery', label: 'Delivery' },
  { id: 'receiving', label: 'Receiving' },
  { id: 'production', label: 'Production' },
]

function shopDateInput(date = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Regina',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

function emptyEntry() {
  return {
    so_number: '',
    customer_name: '',
    lane: 'pickup',
    date: shopDateInput(),
    time: '',
    note: '',
  }
}

function formatEntryDate(value) {
  if (!value) return '—'
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return value
  const date = new Date(Date.UTC(year, month - 1, day, 18))
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Regina',
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  }).format(date)
}

function ShopTvSettings() {
  const [mode, setMode] = useState('off')
  const [pickups, setPickups] = useState('')
  const [deliveries, setDeliveries] = useState('')
  const [pickupAgents, setPickupAgents] = useState('')
  const [deliveryAgents, setDeliveryAgents] = useState('')
  const [agentMeansDelivery, setAgentMeansDelivery] = useState(false)
  const [incomingMode, setIncomingMode] = useState('off')
  const [emailMode, setEmailMode] = useState('off')
  const [reviews, setReviews] = useState([])
  const [fixPo, setFixPo] = useState({})
  const [outlook, setOutlook] = useState(false)
  const [mapping, setMapping] = useState([])
  const [tokens, setTokens] = useState([])
  const [name, setName] = useState('Shop TV')
  const [created, setCreated] = useState(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [entries, setEntries] = useState([])
  const [scheduleReady, setScheduleReady] = useState(false)
  const [entryForm, setEntryForm] = useState(emptyEntry)
  const [editingId, setEditingId] = useState(null)
  const [showDone, setShowDone] = useState(true)

  const apply = (data) => {
    setMode(data.mode === 'on' ? 'on' : 'off')
    setPickups(listToText(data.pickup_shipment_methods))
    setDeliveries(listToText(data.delivery_shipment_methods))
    setPickupAgents(listToText(data.pickup_shipping_agents))
    setDeliveryAgents(listToText(data.delivery_shipping_agents))
    setAgentMeansDelivery(Boolean(data.shipping_agent_means_delivery))
    setIncomingMode(data.incoming_mode === 'on' ? 'on' : 'off')
    setEmailMode(data.email_matching_mode === 'on' ? 'on' : 'off')
    setReviews(data.incoming_reviews || [])
    setOutlook(Boolean(data.outlook_calendar_enabled))
    setMapping(data.mapping || [])
    setTokens(data.tokens || [])
  }

  const loadEntries = async () => {
    try {
      const response = await shopTvApi.listEntries()
      setEntries(response.data.entries || [])
      setScheduleReady(true)
    } catch (err) {
      if (err.response?.status === 404) {
        setEntries([])
        setScheduleReady(false)
        return
      }
      setError(err.response?.data?.detail || 'Could not load schedule entries')
    }
  }

  const load = async () => {
    setError('')
    try {
      const response = await shopTvApi.settings()
      apply(response.data)
      await loadEntries()
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
        incoming_mode: incomingMode,
        email_matching_mode: emailMode,
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

  const setField = (key, value) => {
    setEntryForm((current) => ({ ...current, [key]: value }))
  }

  const resetEntryForm = () => {
    setEntryForm(emptyEntry())
    setEditingId(null)
  }

  const saveEntry = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    const body = {
      so_number: entryForm.so_number.trim(),
      customer_name: entryForm.customer_name.trim(),
      lane: entryForm.lane,
      date: entryForm.date,
      time: entryForm.time || '',
      note: entryForm.note.trim(),
    }
    try {
      if (editingId) {
        await shopTvApi.updateEntry(editingId, body)
      } else {
        await shopTvApi.createEntry(body)
      }
      resetEntryForm()
      await loadEntries()
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Could not save that schedule entry')
    } finally {
      setBusy(false)
    }
  }

  const editEntry = (entry) => {
    setEditingId(entry.id)
    setEntryForm({
      so_number: entry.so_number || '',
      customer_name: entry.customer_name || '',
      lane: entry.lane,
      date: entry.date,
      time: entry.time || '',
      note: entry.note || '',
    })
  }

  const markEntry = async (entry, done) => {
    setBusy(true)
    setError('')
    try {
      await shopTvApi.updateEntry(entry.id, { done })
      await loadEntries()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not update that schedule entry')
    } finally {
      setBusy(false)
    }
  }

  const removeEntry = async (entry) => {
    const label = entry.so_number || entry.customer_name || 'this entry'
    if (!window.confirm(`Remove ${label} from the shop schedule?`)) return
    setBusy(true)
    setError('')
    try {
      await shopTvApi.deleteEntry(entry.id)
      if (editingId === entry.id) resetEntryForm()
      await loadEntries()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not delete that schedule entry')
    } finally {
      setBusy(false)
    }
  }

  const visibleEntries = showDone ? entries : entries.filter((entry) => !entry.done)

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

      <div className="border-t border-gray-200 pt-6 space-y-4">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Shop schedule</h3>
          <p className="mt-1 text-sm text-gray-600">
            Type the day the shop should see. Draft sales orders stay off the board until they are listed here.
            Receiving shows in Incoming. A done row is hidden on the TV. The same sales order on that lane replaces the Business Central row.
            Nothing here is written back to Business Central.
          </p>
        </div>
        {!scheduleReady && (
          <p className="text-sm text-gray-500">Turn the board on to add schedule entries.</p>
        )}
        {scheduleReady && (
          <>
            <form onSubmit={saveEntry} className="grid gap-3 md:grid-cols-2">
              <label className="block text-sm">
                <span className="font-medium text-gray-700">Sales order</span>
                <input
                  value={entryForm.so_number}
                  onChange={(event) => setField('so_number', event.target.value)}
                  placeholder="SO-001278"
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
                />
              </label>
              <label className="block text-sm">
                <span className="font-medium text-gray-700">Customer</span>
                <input
                  value={entryForm.customer_name}
                  onChange={(event) => setField('customer_name', event.target.value)}
                  placeholder="Filled from the sales order when blank"
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
                />
              </label>
              <label className="block text-sm">
                <span className="font-medium text-gray-700">Lane</span>
                <select
                  value={entryForm.lane}
                  onChange={(event) => setField('lane', event.target.value)}
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
                >
                  {ENTRY_LANES.map((lane) => (
                    <option key={lane.id} value={lane.id}>{lane.label}</option>
                  ))}
                </select>
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block text-sm">
                  <span className="font-medium text-gray-700">Date</span>
                  <input
                    type="date"
                    required
                    value={entryForm.date}
                    onChange={(event) => setField('date', event.target.value)}
                    className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
                  />
                </label>
                <label className="block text-sm">
                  <span className="font-medium text-gray-700">Time</span>
                  <input
                    type="time"
                    value={entryForm.time}
                    onChange={(event) => setField('time', event.target.value)}
                    className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
                  />
                </label>
              </div>
              <label className="block text-sm md:col-span-2">
                <span className="font-medium text-gray-700">Note</span>
                <input
                  value={entryForm.note}
                  onChange={(event) => setField('note', event.target.value)}
                  maxLength={200}
                  placeholder="Partial receipt, or ready for install Mon Nov 23"
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
                />
              </label>
              <div className="flex items-center gap-3 md:col-span-2">
                <button
                  type="submit"
                  disabled={busy || !entryForm.date}
                  className="rounded-md bg-odc-600 px-4 py-2 text-sm font-semibold text-white hover:bg-odc-700 disabled:opacity-50"
                >
                  {editingId ? 'Save entry' : 'Add entry'}
                </button>
                {editingId && (
                  <button type="button" onClick={resetEntryForm} className="text-sm font-medium text-gray-600">
                    Cancel
                  </button>
                )}
              </div>
            </form>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={showDone}
                onChange={(event) => setShowDone(event.target.checked)}
              />
              Show done entries
            </label>
            <ul className="divide-y divide-gray-100">
              {visibleEntries.length === 0 && (
                <li className="py-2 text-sm text-gray-500">No schedule entries yet.</li>
              )}
              {visibleEntries.map((entry) => {
                const lane = ENTRY_LANES.find((item) => item.id === entry.lane)
                return (
                  <li key={entry.id} className={`flex flex-wrap items-center justify-between gap-3 py-3 text-sm ${entry.done ? 'text-gray-400' : ''}`}>
                    <div>
                      <p className="font-medium text-gray-900">
                        {entry.so_number || 'No sales order'}
                        <span className="ml-2 font-normal text-gray-500">{lane ? lane.label : entry.lane}</span>
                        {entry.done && <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-xs font-semibold uppercase text-gray-500">Done</span>}
                      </p>
                      <p className="text-gray-600">
                        {entry.customer_name || 'No customer'}
                        {' · '}
                        {formatEntryDate(entry.date)}
                        {entry.time ? ` ${entry.time}` : ''}
                      </p>
                      {entry.note && <p className="text-gray-500">{entry.note}</p>}
                    </div>
                    <div className="flex items-center gap-2">
                      <button type="button" onClick={() => editEntry(entry)} disabled={busy} className="rounded-md border border-gray-300 px-3 py-1.5 font-medium text-gray-700 disabled:opacity-50">
                        Edit
                      </button>
                      <button type="button" onClick={() => markEntry(entry, !entry.done)} disabled={busy} className="rounded-md border border-gray-300 px-3 py-1.5 font-medium text-gray-700 disabled:opacity-50">
                        {entry.done ? 'Reopen' : 'Mark done'}
                      </button>
                      <button type="button" onClick={() => removeEntry(entry)} disabled={busy} className="rounded-md border border-red-300 px-3 py-1.5 font-medium text-red-700 disabled:opacity-50">
                        Delete
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          </>
        )}
      </div>

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

      <div className="border-t border-gray-200 pt-6 space-y-3">
        <h3 className="text-base font-semibold text-gray-900">Incoming</h3>
        <p className="text-sm text-gray-600">
          Off, Incoming and Arriving from Upwardor are hidden. On, open Upwardor purchase orders get their own block. Other vendors stay in Incoming. Email matching stays off until you turn it on. It reads ship notices and does not change Business Central.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium text-gray-700">Incoming lane</span>
          {['off', 'on'].map((value) => (
            <button key={value} type="button" onClick={() => setIncomingMode(value)} className={`rounded-md px-3 py-1.5 text-sm font-semibold ${incomingMode === value ? 'bg-odc-800 text-white' : 'bg-gray-100 text-gray-700'}`}>
              {value === 'on' ? 'On' : 'Off'}
            </button>
          ))}
          <span className="ml-4 text-sm font-medium text-gray-700">Email matching</span>
          {['off', 'on'].map((value) => (
            <button key={`mail-${value}`} type="button" onClick={() => setEmailMode(value)} className={`rounded-md px-3 py-1.5 text-sm font-semibold ${emailMode === value ? 'bg-odc-800 text-white' : 'bg-gray-100 text-gray-700'}`}>
              {value === 'on' ? 'On' : 'Off'}
            </button>
          ))}
        </div>
        <ul className="divide-y divide-gray-100">
          {reviews.length === 0 && <li className="py-2 text-sm text-gray-500">No shipping emails waiting for review.</li>}
          {reviews.map((review) => (
            <li key={review.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
              <div>
                <p className="font-medium text-gray-900">{review.subject || 'Shipping email'}</p>
                <p className="text-gray-500">{review.reason}</p>
              </div>
              <div className="flex items-center gap-2">
                <input
                  value={fixPo[review.id] || review.proposed_po || ''}
                  onChange={(event) => setFixPo({ ...fixPo, [review.id]: event.target.value })}
                  placeholder="PO-000962"
                  className="w-32 rounded-md border border-gray-300 px-2 py-1"
                />
                <button
                  type="button"
                  className="rounded-md bg-odc-600 px-3 py-1.5 font-semibold text-white"
                  onClick={async () => {
                    const po = (fixPo[review.id] || '').trim()
                    if (po) await shopTvApi.fixIncoming(review.id, po)
                    else await shopTvApi.acceptIncoming(review.id)
                    await load()
                  }}
                >
                  {fixPo[review.id] ? 'Fix' : 'Accept'}
                </button>
                <button
                  type="button"
                  className="rounded-md border border-gray-300 px-3 py-1.5 font-semibold text-gray-700"
                  onClick={async () => {
                    await shopTvApi.rejectIncoming(review.id)
                    await load()
                  }}
                >
                  Reject
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>

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
