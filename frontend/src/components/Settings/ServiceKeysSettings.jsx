import { useEffect, useState } from 'react'
import { serviceKeysApi } from '../../api/client'

function formatWhen(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

function ServiceKeysSettings() {
  const [keys, setKeys] = useState([])
  const [audit, setAudit] = useState([])
  const [name, setName] = useState('')
  const [expires, setExpires] = useState('')
  const [plaintext, setPlaintext] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)

  const load = async () => {
    setError('')
    try {
      const [keyRes, auditRes] = await Promise.all([
        serviceKeysApi.list(),
        serviceKeysApi.audit(40),
      ])
      setKeys(keyRes.data || [])
      setAudit(auditRes.data || [])
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load service keys')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const createKey = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    setCopied(false)
    try {
      const body = { name: name.trim() }
      if (expires) {
        body.expires_at = new Date(expires).toISOString()
      }
      const response = await serviceKeysApi.create(body)
      setPlaintext(response.data.plaintext || '')
      setName('')
      setExpires('')
      await load()
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Could not create the key')
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (row) => {
    const ok = window.confirm(
      `Revoke "${row.name}"? The automation will stop working on its next request. This cannot be undone.`
    )
    if (!ok) return
    setError('')
    try {
      await serviceKeysApi.revoke(row.id)
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not revoke the key')
    }
  }

  const copyKey = async () => {
    try {
      await navigator.clipboard.writeText(plaintext)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-medium text-gray-900">Service keys</h2>
        <p className="mt-1 text-sm text-gray-500">
          A service key lets the automation call the staff portal without logging in as a person.
          A staff login expires. A service key lasts until you revoke it, unless you set an end date.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
          <h3 className="text-sm font-medium text-gray-900">What the key can do</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-600">
            <li>Read sales orders, quotes, and quote reviews</li>
            <li>Read inventory and catalog items</li>
            <li>Read purchasing needs and which sales orders already have a PO</li>
            <li>List, check, and edit lines on Draft purchase orders</li>
            <li>Create a Draft PO when send_email is false (it does not email anyone)</li>
            <li>Save an unsent Outlook draft for a Draft PO that already exists</li>
            <li>Run the vendor acknowledgement check</li>
          </ul>
        </div>
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
          <h3 className="text-sm font-medium text-gray-900">What the key cannot do</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-600">
            <li>Manage users or change settings</li>
            <li>Delete, post, or release Business Central documents</li>
            <li>Approve quotes, send email, or call anything not on the list</li>
          </ul>
          <p className="mt-3 text-sm text-gray-600">
            Send the key as <code className="text-xs">Authorization: Bearer osk_...</code> or
            as the <code className="text-xs">X-API-Key</code> header.
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {plaintext && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-4">
          <h3 className="text-sm font-medium text-amber-900">Copy this key now</h3>
          <p className="mt-1 text-sm text-amber-800">
            This is the only time the portal will show it. Store it with the automation.
            If you lose it, revoke this key and create a new one.
          </p>
          <textarea
            readOnly
            value={plaintext}
            className="mt-3 w-full rounded border border-amber-300 bg-white p-2 font-mono text-sm text-gray-900"
            rows={3}
          />
          <button
            type="button"
            onClick={copyKey}
            className="mt-2 rounded bg-amber-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-800"
          >
            {copied ? 'Copied' : 'Copy key'}
          </button>
        </div>
      )}

      <form onSubmit={createKey} className="space-y-4 rounded-lg border border-gray-200 p-4">
        <h3 className="text-sm font-medium text-gray-900">Create a key</h3>
        <div>
          <label htmlFor="service-key-name" className="block text-sm text-gray-700">
            Name
          </label>
          <input
            id="service-key-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Hourly PO check"
            required
            className="mt-1 w-full max-w-md rounded border border-gray-300 px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-gray-500">
            A label so you can tell keys apart. The key can do the automation tasks listed above.
          </p>
        </div>
        <div>
          <label htmlFor="service-key-expires" className="block text-sm text-gray-700">
            Expires (optional)
          </label>
          <input
            id="service-key-expires"
            type="datetime-local"
            value={expires}
            onChange={(event) => setExpires(event.target.value)}
            className="mt-1 rounded border border-gray-300 px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-gray-500">Leave blank and the key does not expire.</p>
        </div>
        <button
          type="submit"
          disabled={busy || !name.trim()}
          className="rounded bg-odc-600 px-4 py-2 text-sm font-medium text-white hover:bg-odc-700 disabled:opacity-50"
        >
          {busy ? 'Creating…' : 'Create key'}
        </button>
      </form>

      <div>
        <h3 className="text-sm font-medium text-gray-900">Keys</h3>
        {loading ? (
          <p className="mt-2 text-sm text-gray-500">Loading…</p>
        ) : keys.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No service keys yet.</p>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b text-xs uppercase tracking-wide text-gray-500">
                  <th className="py-2 pr-4">Name</th>
                  <th className="py-2 pr-4">Starts with</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Created</th>
                  <th className="py-2 pr-4">Last used</th>
                  <th className="py-2 pr-4">Expires</th>
                  <th className="py-2"> </th>
                </tr>
              </thead>
              <tbody>
                {keys.map((row) => (
                  <tr key={row.id} className="border-b border-gray-100">
                    <td className="py-2 pr-4 font-medium text-gray-900">{row.name}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-gray-600">{row.key_prefix}</td>
                    <td className="py-2 pr-4">
                      {row.status === 'active' ? (
                        <span className="text-green-700">Active</span>
                      ) : (
                        <span className="text-gray-500">Revoked</span>
                      )}
                    </td>
                    <td className="py-2 pr-4 text-gray-600">{formatWhen(row.created_at)}</td>
                    <td className="py-2 pr-4 text-gray-600">{formatWhen(row.last_used_at)}</td>
                    <td className="py-2 pr-4 text-gray-600">
                      {row.expires_at ? formatWhen(row.expires_at) : 'Never'}
                    </td>
                    <td className="py-2 text-right">
                      {row.status === 'active' && (
                        <button
                          type="button"
                          onClick={() => revoke(row)}
                          className="text-sm font-medium text-red-600 hover:text-red-800"
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <h3 className="text-sm font-medium text-gray-900">Recent activity</h3>
        <p className="mt-1 text-sm text-gray-500">
          Each time a service key calls the portal, the key name, the page it called, and the time are saved here.
        </p>
        {audit.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No activity yet.</p>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b text-xs uppercase tracking-wide text-gray-500">
                  <th className="py-2 pr-4">When</th>
                  <th className="py-2 pr-4">Key</th>
                  <th className="py-2 pr-4">Call</th>
                  <th className="py-2">Result</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((row) => (
                  <tr key={row.id} className="border-b border-gray-100">
                    <td className="py-2 pr-4 text-gray-600">{formatWhen(row.created_at)}</td>
                    <td className="py-2 pr-4 text-gray-900">{row.key_name || row.key_prefix || 'Unknown'}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-gray-700">
                      {row.method} {row.path}
                    </td>
                    <td className="py-2 text-gray-600">
                      {row.decision === 'allowed' ? 'Allowed' : 'Blocked'} ({row.status_code})
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default ServiceKeysSettings
