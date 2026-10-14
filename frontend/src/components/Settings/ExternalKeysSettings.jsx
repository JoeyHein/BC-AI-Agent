import { useEffect, useState } from 'react'
import { externalKeysApi } from '../../api/client'

function formatWhen(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

function errorMessage(err, fallback) {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0]
    if (typeof first === 'string') return first
    if (first?.msg) return first.msg
  }
  return fallback
}

function ExternalKeysSettings() {
  const [keys, setKeys] = useState([])
  const [name, setName] = useState('')
  const [accountCode, setAccountCode] = useState('')
  const [plaintext, setPlaintext] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionId, setActionId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)

  const load = async ({ clearError = true } = {}) => {
    if (clearError) setError('')
    try {
      const response = await externalKeysApi.list()
      setKeys(response.data || [])
    } catch (err) {
      setError(errorMessage(err, 'Could not load external API keys'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const revealKey = (secret) => {
    if (!secret) {
      setPlaintext('')
      setError('The server did not return a key. Nothing was stored for you to copy.')
      return false
    }
    setCopied(false)
    setPlaintext(secret)
    return true
  }

  const createKey = async (event) => {
    event.preventDefault()
    const trimmedName = name.trim()
    const trimmedAccount = accountCode.trim()
    if (!trimmedName || !trimmedAccount) return
    setBusy(true)
    setError('')
    try {
      const response = await externalKeysApi.create({
        name: trimmedName,
        supplier_account_code: trimmedAccount,
      })
      const shown = revealKey(response.data?.plaintext)
      if (shown) {
        setName('')
        setAccountCode('')
      }
      await load({ clearError: shown })
    } catch (err) {
      setError(errorMessage(err, 'Could not create the key'))
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (row) => {
    const ok = window.confirm(
      `Revoke "${row.name}" (${row.key_prefix})? Partner systems sending this key will be rejected on their next request. This cannot be undone.`
    )
    if (!ok) return
    setActionId(row.id)
    setError('')
    try {
      await externalKeysApi.revoke(row.id)
      await load()
    } catch (err) {
      setError(errorMessage(err, 'Could not revoke the key'))
    } finally {
      setActionId(null)
    }
  }

  const rotate = async (row) => {
    const ok = window.confirm(
      `Rotate "${row.name}"? The current key stops working immediately. A new key is shown once and will not be shown again. Update the partner system with the new key.`
    )
    if (!ok) return
    setActionId(row.id)
    setError('')
    try {
      const response = await externalKeysApi.rotate(row.id)
      const shown = revealKey(response.data?.plaintext)
      await load({ clearError: shown })
    } catch (err) {
      setError(errorMessage(err, 'Could not rotate the key'))
    } finally {
      setActionId(null)
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

  const working = busy || actionId !== null

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-medium text-gray-900">External API keys</h2>
        <p className="mt-1 text-sm text-gray-500">
          Staff service keys are for internal use; external keys are sent in the{' '}
          <code className="text-xs">X-Service-AI-Key</code> header by partner systems like Elevated Doors.
        </p>
      </div>

      {error && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {plaintext && (
        <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-4">
          <h3 className="text-sm font-medium text-amber-900">Copy this key now</h3>
          <p className="mt-1 text-sm text-amber-800">
            This is the full key. It will not be shown again. Copy it now and store it with the partner system.
            If you lose it, rotate the key and update the partner with the new one.
          </p>
          <textarea
            readOnly
            value={plaintext}
            aria-label="External API key"
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
          <label htmlFor="external-key-name" className="block text-sm text-gray-700">
            Name
          </label>
          <input
            id="external-key-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Elevated Doors"
            maxLength={200}
            required
            className="mt-1 w-full max-w-md rounded border border-gray-300 px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-gray-500">
            A label so you can tell keys apart.
          </p>
        </div>
        <div>
          <label htmlFor="external-key-account" className="block text-sm text-gray-700">
            BC customer number
          </label>
          <input
            id="external-key-account"
            value={accountCode}
            onChange={(event) => setAccountCode(event.target.value)}
            placeholder="ED-001"
            maxLength={80}
            required
            className="mt-1 w-full max-w-md rounded border border-gray-300 px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-gray-500">
            The number (e.g. ED-001) must match a real BC customer number.
          </p>
        </div>
        <button
          type="submit"
          disabled={working || !name.trim() || !accountCode.trim()}
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
          <p className="mt-2 text-sm text-gray-500">No external API keys yet.</p>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b text-xs uppercase tracking-wide text-gray-500">
                  <th className="py-2 pr-4">Prefix</th>
                  <th className="py-2 pr-4">Name</th>
                  <th className="py-2 pr-4">BC customer number</th>
                  <th className="py-2 pr-4">Created</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2"> </th>
                </tr>
              </thead>
              <tbody>
                {keys.map((row) => (
                  <tr key={row.id} className="border-b border-gray-100">
                    <td className="py-2 pr-4 font-mono text-xs text-gray-600">{row.key_prefix}</td>
                    <td className="py-2 pr-4 font-medium text-gray-900">{row.name}</td>
                    <td className="py-2 pr-4 text-gray-700">{row.supplier_account_code}</td>
                    <td className="py-2 pr-4 text-gray-600">{formatWhen(row.created_at)}</td>
                    <td className="py-2 pr-4">
                      {row.status === 'active' ? (
                        <span className="text-green-700">Active</span>
                      ) : (
                        <span className="text-gray-500">Revoked</span>
                      )}
                    </td>
                    <td className="py-2 text-right whitespace-nowrap">
                      {row.status === 'active' && (
                        <>
                          <button
                            type="button"
                            onClick={() => rotate(row)}
                            disabled={working}
                            className="mr-3 text-sm font-medium text-odc-600 hover:text-odc-800 disabled:opacity-50"
                          >
                            Rotate
                          </button>
                          <button
                            type="button"
                            onClick={() => revoke(row)}
                            disabled={working}
                            className="text-sm font-medium text-red-600 hover:text-red-800 disabled:opacity-50"
                          >
                            Revoke
                          </button>
                        </>
                      )}
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

export default ExternalKeysSettings
