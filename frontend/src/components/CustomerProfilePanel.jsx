import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { customersApi } from '../api/client'

const MODE_HELP = {
  off: 'Off. Quotes ignore this profile. This is the production default.',
  shadow: 'Shadow. The profile is calculated and saved on the quote, and the quote sent to Business Central stays the old one.',
  on: 'On. Silent fields use this profile. A locked value wins, and an unmatched sender is held instead of priced at retail.',
}

function confidenceLabel(field) {
  if (!field || field.confidence == null) return null
  return `${Math.round(Number(field.confidence) * 100)}%`
}

export default function CustomerProfilePanel({ bcCustomerId }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState(null)
  const [message, setMessage] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['customer-profile', bcCustomerId],
    queryFn: async () => (await customersApi.getOrderingProfile(bcCustomerId)).data,
    enabled: !!bcCustomerId,
  })

  useEffect(() => {
    if (!data) return
    setDraft({
      fields: data.fields || {},
      contacts: data.contacts || [],
      email_domains: data.email_domains || [],
      ship_to: data.ship_to || { value: {}, locked: false },
      contacts_locked: !!data.contacts_locked,
      domains_locked: !!data.domains_locked,
      ship_to_locked: !!data.ship_to_locked,
    })
  }, [data])

  const save = useMutation({
    mutationFn: (body) => customersApi.saveOrderingProfile(bcCustomerId, body),
    onSuccess: (response) => {
      queryClient.setQueryData(['customer-profile', bcCustomerId], response.data)
      setMessage('Profile saved. A changed value is locked.')
    },
    onError: (err) => setMessage(err.response?.data?.detail || 'Save failed'),
  })

  const setMode = useMutation({
    mutationFn: (mode) => customersApi.setProfileQuotingMode(mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customer-profile', bcCustomerId] })
      setMessage('Quoting mode updated. It applies to the next quote.')
    },
    onError: (err) => setMessage(err.response?.data?.detail || 'Could not change mode'),
  })

  if (!bcCustomerId) {
    return (
      <div className="bg-white shadow rounded-lg p-4 text-sm text-gray-500">
        Link a Business Central customer to edit an ordering profile.
      </div>
    )
  }
  if (isLoading || !draft) {
    return <div className="bg-white shadow rounded-lg p-4 text-sm text-gray-500">Loading ordering profile…</div>
  }
  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
        {error.response?.data?.detail || 'Could not load the ordering profile'}
      </div>
    )
  }

  const catalog = data.catalog || []
  const mode = data.quoting_mode || 'off'

  function fieldValue(key) {
    return draft.fields[key]?.value ?? ''
  }

  function updateField(key, patch) {
    setDraft((prev) => {
      const current = prev.fields[key] || {}
      return {
        ...prev,
        fields: { ...prev.fields, [key]: { ...current, ...patch } },
      }
    })
  }

  function saveProfile() {
    const fields = {}
    catalog.forEach((item) => {
      const current = draft.fields[item.key] || {}
      fields[item.key] = {
        value: current.value ?? '',
        locked: !!current.locked,
      }
    })
    save.mutate({
      fields,
      contacts: draft.contacts,
      email_domains: draft.email_domains,
      ship_to: {
        ...(draft.ship_to?.value || {}),
        locked: !!draft.ship_to_locked,
      },
      contacts_locked: draft.contacts_locked,
      domains_locked: draft.domains_locked,
      ship_to_locked: draft.ship_to_locked,
    })
  }

  return (
    <div className="bg-white shadow rounded-lg p-6 space-y-5" data-testid="customer-profile-panel">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Ordering profile</h2>
          <p className="mt-1 text-sm text-gray-500">
            {data.company_name || bcCustomerId}
            {data.customer_number ? ` · ${data.customer_number}` : ''}
            {data.price_group ? ` · price group ${data.price_group}` : ''}
          </p>
          <p className="mt-1 text-xs text-gray-400">
            {data.documents_seen || 0} history documents
            {data.last_seeded_at ? ` · seeded ${data.last_seeded_at}` : ''}
          </p>
        </div>
        <label className="text-sm text-gray-700">
          <span className="block text-xs font-medium text-gray-500 mb-1">Quoting mode</span>
          <select
            aria-label="Quoting mode"
            value={mode}
            onChange={(event) => setMode.mutate(event.target.value)}
            className="border border-gray-300 rounded-md px-2 py-1 text-sm"
          >
            <option value="off">Off</option>
            <option value="shadow">Shadow</option>
            <option value="on">On</option>
          </select>
        </label>
      </div>
      <p className="text-sm text-gray-600">{MODE_HELP[mode]}</p>

      <div className="space-y-3">
        {catalog.map((item) => {
          const stored = data.fields?.[item.key]
          const value = fieldValue(item.key)
          return (
            <div key={item.key} className="grid grid-cols-1 md:grid-cols-12 gap-2 items-center border-b border-gray-100 pb-3">
              <div className="md:col-span-3 text-sm font-medium text-gray-800">{item.label}</div>
              <div className="md:col-span-3">
                {item.choices?.length ? (
                  <select
                    aria-label={item.label}
                    value={value}
                    onChange={(event) => updateField(item.key, { value: event.target.value })}
                    className="w-full border border-gray-300 rounded-md px-2 py-1 text-sm"
                  >
                    <option value="">Not set</option>
                    {item.choices.map((choice) => (
                      <option key={choice} value={choice}>{choice}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    aria-label={item.label}
                    value={value}
                    onChange={(event) => updateField(item.key, { value: event.target.value })}
                    className="w-full border border-gray-300 rounded-md px-2 py-1 text-sm"
                  />
                )}
              </div>
              <label className="md:col-span-2 flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  aria-label={`Lock ${item.label}`}
                  checked={!!draft.fields[item.key]?.locked}
                  onChange={(event) => updateField(item.key, { locked: event.target.checked })}
                />
                Lock
              </label>
              <div className="md:col-span-4 text-xs text-gray-500">
                {stored?.evidence || 'No history yet'}
                {confidenceLabel(stored) ? ` · ${confidenceLabel(stored)}` : ''}
                {stored?.locked ? ' · locked' : ''}
                {stored?.source ? ` · ${stored.source}` : ''}
              </div>
            </div>
          )
        })}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-900">Quote and PO contacts</h3>
            <label className="text-xs text-gray-600 flex items-center gap-1">
              <input
                type="checkbox"
                checked={draft.contacts_locked}
                onChange={(event) => setDraft({ ...draft, contacts_locked: event.target.checked })}
              />
              Lock list
            </label>
          </div>
          <ul className="mt-2 space-y-2">
            {draft.contacts.map((contact, index) => (
              <li key={`${contact.email}-${index}`} className="flex gap-2">
                <input
                  aria-label="Contact email"
                  value={contact.email}
                  onChange={(event) => {
                    const contacts = [...draft.contacts]
                    contacts[index] = { ...contact, email: event.target.value }
                    setDraft({ ...draft, contacts })
                  }}
                  className="flex-1 border border-gray-300 rounded-md px-2 py-1 text-sm"
                />
                <select
                  aria-label="Contact role"
                  value={contact.role || 'quote'}
                  onChange={(event) => {
                    const contacts = [...draft.contacts]
                    contacts[index] = { ...contact, role: event.target.value }
                    setDraft({ ...draft, contacts })
                  }}
                  className="border border-gray-300 rounded-md px-2 py-1 text-sm"
                >
                  <option value="quote">Quote</option>
                  <option value="po">PO</option>
                  <option value="both">Both</option>
                </select>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="mt-2 text-sm text-odc-700"
            onClick={() => setDraft({
              ...draft,
              contacts: [...draft.contacts, { email: '', role: 'quote', name: '' }],
            })}
          >
            Add contact
          </button>
        </div>
        <div>
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-900">Email domains</h3>
            <label className="text-xs text-gray-600 flex items-center gap-1">
              <input
                type="checkbox"
                checked={draft.domains_locked}
                onChange={(event) => setDraft({ ...draft, domains_locked: event.target.checked })}
              />
              Lock
            </label>
          </div>
          <textarea
            aria-label="Email domains"
            value={(draft.email_domains || []).join('\n')}
            onChange={(event) => setDraft({
              ...draft,
              email_domains: event.target.value.split('\n').map((line) => line.trim()).filter(Boolean),
            })}
            rows={4}
            className="mt-2 w-full border border-gray-300 rounded-md px-2 py-1 text-sm"
            placeholder="gnb.example"
          />
          <h3 className="mt-3 text-sm font-medium text-gray-900">Ship-to</h3>
          <input
            aria-label="Ship-to city"
            value={draft.ship_to?.value?.city || ''}
            onChange={(event) => setDraft({
              ...draft,
              ship_to: { ...draft.ship_to, value: { ...(draft.ship_to?.value || {}), city: event.target.value } },
            })}
            className="mt-2 w-full border border-gray-300 rounded-md px-2 py-1 text-sm"
            placeholder="City"
          />
          <p className="mt-1 text-xs text-gray-500">{data.ship_to?.evidence || ''}</p>
        </div>
      </div>

      {message && <p className="text-sm text-gray-700">{message}</p>}
      <button
        type="button"
        onClick={saveProfile}
        disabled={save.isPending}
        className="inline-flex items-center px-4 py-2 rounded-md text-sm font-medium text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
      >
        {save.isPending ? 'Saving…' : 'Save profile'}
      </button>
    </div>
  )
}
