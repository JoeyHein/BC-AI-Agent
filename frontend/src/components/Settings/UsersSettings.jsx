import { useEffect, useMemo, useState } from 'react'
import { usersApi } from '../../api/client'
import { useAuth } from '../../contexts/AuthContext'

function imply(flags) {
  const out = { ...flags }
  Object.keys(out).forEach((key) => {
    const [area, level] = key.split('.')
    if (level !== 'view') return
    if (out[`${area}.edit`] || out[`${area}.manage`] || out[`${area}.send`]) out[key] = true
  })
  return out
}

function groupOf(spec) {
  const groups = []
  const seen = new Map()
  ;(spec || []).forEach((item) => {
    if (!seen.has(item.group)) {
      seen.set(item.group, groups.length)
      groups.push({ name: item.group, items: [] })
    }
    groups[seen.get(item.group)].items.push(item)
  })
  return groups
}

function statusOf(row) {
  if (row.invite_pending) return { label: 'Invite sent', className: 'bg-amber-50 text-amber-800' }
  if (!row.is_active) return { label: 'Disabled', className: 'bg-gray-100 text-gray-600' }
  return { label: 'Active', className: 'bg-emerald-50 text-emerald-800' }
}

function absoluteLink(path) {
  if (!path) return ''
  return `${window.location.origin}${path}`
}

function UsersSettings() {
  const { user: actor, can } = useAuth()
  const canManage = can('users.manage')
  const [catalog, setCatalog] = useState({ presets: [], permissions: [] })
  const [rows, setRows] = useState([])
  const [audit, setAudit] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [invite, setInvite] = useState({ name: '', email: '', role: 'viewer', permissions: {} })
  const [link, setLink] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const presets = useMemo(() => {
    const hasOwner = rows.some((row) => row.role === 'owner' && row.is_active)
    return catalog.presets.filter((preset) => !preset.owner_only || actor?.role === 'owner' || (!hasOwner && actor?.role === 'admin'))
  }, [catalog.presets, actor?.role, rows])
  const groups = useMemo(() => groupOf(catalog.permissions), [catalog.permissions])
  const selected = rows.find((row) => row.id === selectedId) || null

  const load = async () => {
    setError('')
    try {
      const [catalogRes, userRes, auditRes] = await Promise.all([
        usersApi.catalog(),
        usersApi.list(),
        usersApi.audit(40),
      ])
      setCatalog(catalogRes.data || { presets: [], permissions: [] })
      setRows(userRes.data || [])
      setAudit(auditRes.data || [])
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load staff')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const presetById = (id) => catalog.presets.find((preset) => preset.id === id)

  const openRow = (row) => {
    setSelectedId(row.id)
    setInviteOpen(false)
    setLink(null)
    setDraft({ role: row.role, permissions: { ...row.permissions } })
  }

  const startInvite = () => {
    const preset = presetById('viewer') || catalog.presets[0]
    setInviteOpen(true)
    setSelectedId(null)
    setDraft(null)
    setLink(null)
    setInvite({
      name: '',
      email: '',
      role: preset?.id || 'viewer',
      permissions: { ...(preset?.permissions || {}) },
    })
  }

  const setInviteRole = (role) => {
    const preset = presetById(role)
    setInvite((current) => ({
      ...current,
      role,
      permissions: { ...(preset?.permissions || current.permissions) },
    }))
  }

  const setDraftRole = (role) => {
    const preset = presetById(role)
    setDraft((current) => ({
      role,
      permissions: { ...(preset?.permissions || current?.permissions || {}) },
    }))
  }

  const toggleFlag = (setter, key) => {
    setter((current) => {
      const next = { ...current.permissions, [key]: !current.permissions[key] }
      return { ...current, permissions: imply(next) }
    })
  }

  const showLink = (payload, fallback) => {
    const path = payload?.setup_path
    const url = absoluteLink(path)
    setLink({
      url,
      emailed: Boolean(payload?.email_sent),
      fallback,
    })
    setNotice(payload?.email_sent ? 'Email sent. The link below works even if the email is delayed.' : fallback)
  }

  const sendInvite = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const response = await usersApi.invite({
        name: invite.name.trim(),
        email: invite.email.trim(),
        role: invite.role,
        permissions: invite.permissions,
      })
      showLink(response.data, 'Setup link created. Copy it if the email did not go out.')
      setInviteOpen(false)
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not send the invite')
    } finally {
      setBusy(false)
    }
  }

  const saveDraft = async () => {
    if (!selected || !draft) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await usersApi.update(selected.id, {
        role: draft.role,
        permissions: draft.permissions,
      })
      setNotice('Access saved.')
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save access')
    } finally {
      setBusy(false)
    }
  }

  const runAction = async (action) => {
    if (!selected) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const response = await action(selected.id)
      if (response?.data?.setup_path) {
        showLink(response.data, 'Link ready. Copy it from this page.')
      } else {
        setNotice('Updated.')
      }
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || 'That change was refused')
    } finally {
      setBusy(false)
    }
  }

  const copyLink = async () => {
    if (!link?.url) return
    try {
      await navigator.clipboard.writeText(link.url)
      setNotice('Link copied.')
    } catch {
      setNotice('Select the link and copy it.')
    }
  }

  if (loading) return <p className="text-sm text-gray-500">Loading staff…</p>

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Users</h2>
          <p className="text-sm text-gray-500">
            Invite staff with a setup link. They choose their own password. Disable a login to keep its history.
          </p>
        </div>
        {canManage && (
          <button
            type="button"
            onClick={startInvite}
            className="rounded-md bg-odc-600 px-3 py-2 text-sm font-medium text-white hover:bg-odc-700"
          >
            Invite staff
          </button>
        )}
      </div>

      {!canManage && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
          You can view staff access. An owner has to invite people or change permissions.
        </p>
      )}
      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      {notice && <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</p>}
      {link?.url && (
        <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-sm">
          <p className="font-medium text-gray-900">Setup link for this browser</p>
          <p className="mt-1 break-all text-gray-700">{link.url}</p>
          <button type="button" onClick={copyLink} className="mt-2 text-sm font-medium text-odc-700 hover:text-odc-900">
            Copy link
          </button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
          {rows.map((row) => {
            const status = statusOf(row)
            const active = row.id === selectedId
            return (
              <li key={row.id}>
                <button
                  type="button"
                  onClick={() => openRow(row)}
                  className={`w-full px-3 py-3 text-left ${active ? 'bg-odc-50' : 'hover:bg-gray-50'}`}
                >
                  <span className="block truncate text-sm font-medium text-gray-900">{row.name || row.email}</span>
                  <span className="block truncate text-xs text-gray-500">{row.email}</span>
                  <span className="mt-1 flex items-center gap-2">
                    <span className="text-xs capitalize text-gray-600">{row.role}</span>
                    {row.permissions_custom && <span className="text-xs text-odc-700">Custom</span>}
                    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${status.className}`}>{status.label}</span>
                  </span>
                </button>
              </li>
            )
          })}
          {rows.length === 0 && <li className="px-3 py-4 text-sm text-gray-500">No staff logins yet.</li>}
        </ul>

        <div>
          {inviteOpen && canManage && (
            <form className="space-y-4" onSubmit={sendInvite}>
              <h3 className="text-base font-medium text-gray-900">New staff login</h3>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block text-sm text-gray-700">
                  Name
                  <input
                    required
                    value={invite.name}
                    onChange={(event) => setInvite({ ...invite, name: event.target.value })}
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  />
                </label>
                <label className="block text-sm text-gray-700">
                  Email
                  <input
                    required
                    type="email"
                    value={invite.email}
                    onChange={(event) => setInvite({ ...invite, email: event.target.value })}
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  />
                </label>
              </div>
              <RoleAndFlags
                presets={presets}
                groups={groups}
                role={invite.role}
                permissions={invite.permissions}
                onRole={setInviteRole}
                onToggle={(key) => toggleFlag(setInvite, key)}
              />
              <button
                type="submit"
                disabled={busy}
                className="rounded-md bg-odc-600 px-3 py-2 text-sm font-medium text-white hover:bg-odc-700 disabled:opacity-50"
              >
                {busy ? 'Sending…' : 'Send setup link'}
              </button>
            </form>
          )}

          {selected && draft && (
            <div className="space-y-4">
              <div>
                <h3 className="text-base font-medium text-gray-900">{selected.name || selected.email}</h3>
                <p className="text-sm text-gray-500">{selected.email}</p>
              </div>
              <RoleAndFlags
                presets={presets}
                groups={groups}
                role={draft.role}
                permissions={draft.permissions}
                disabled={!canManage}
                selfId={actor?.id === selected.id}
                onRole={setDraftRole}
                onToggle={(key) => toggleFlag(setDraft, key)}
              />
              {canManage && (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={saveDraft}
                    className="rounded-md bg-odc-600 px-3 py-2 text-sm font-medium text-white hover:bg-odc-700 disabled:opacity-50"
                  >
                    Save access
                  </button>
                  {selected.invite_pending || !selected.is_active ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => runAction(usersApi.setupLink)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                    >
                      Send setup link
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => runAction(usersApi.passwordReset)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                    >
                      Send password reset
                    </button>
                  )}
                  {selected.is_active ? (
                    <button
                      type="button"
                      disabled={busy || actor?.id === selected.id}
                      onClick={() => runAction(usersApi.disable)}
                      className="rounded-md border border-red-200 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                    >
                      Disable
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busy || selected.invite_pending}
                      onClick={() => runAction(usersApi.enable)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                    >
                      Re-enable
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {!inviteOpen && !selected && (
            <p className="text-sm text-gray-500">Select a person to review their access.</p>
          )}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-medium text-gray-900">Access changes</h3>
        <ul className="mt-2 divide-y divide-gray-100 text-sm">
          {audit.map((row) => (
            <li key={row.id} className="py-2">
              <span className="font-medium text-gray-800">{row.action}</span>
              <span className="text-gray-500"> · {row.actor_email || 'system'} → {row.target_email}</span>
              <span className="block text-xs text-gray-400">{row.created_at ? new Date(row.created_at).toLocaleString() : ''}</span>
            </li>
          ))}
          {audit.length === 0 && <li className="py-2 text-gray-500">No access changes recorded yet.</li>}
        </ul>
      </div>
    </div>
  )
}

function RoleAndFlags({ presets, groups, role, permissions, onRole, onToggle, disabled, selfId }) {
  return (
    <div className="space-y-4">
      <label className="block text-sm text-gray-700">
        Preset
        <select
          value={role}
          disabled={disabled}
          onChange={(event) => onRole(event.target.value)}
          className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm disabled:bg-gray-50"
        >
          {presets.map((preset) => (
            <option key={preset.id} value={preset.id}>{preset.label}</option>
          ))}
          {role && !presets.some((preset) => preset.id === role) && (
            <option value={role}>{role}</option>
          )}
        </select>
      </label>
      <p className="text-xs text-gray-500">{presets.find((preset) => preset.id === role)?.description}</p>
      <div className="grid gap-4 sm:grid-cols-2">
        {groups.map((group) => (
          <fieldset key={group.name} className="rounded-md border border-gray-200 p-3">
            <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-gray-500">{group.name}</legend>
            <div className="mt-2 space-y-1">
              {group.items.map((item) => {
                const locked = selfId && item.key === 'users.manage'
                const [area, level] = item.key.split('.')
                const implied = level === 'view' && (
                  permissions?.[`${area}.edit`] || permissions?.[`${area}.manage`] || permissions?.[`${area}.send`]
                )
                return (
                  <label key={item.key} className="flex items-start gap-2 text-sm text-gray-700">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={Boolean(permissions?.[item.key])}
                      disabled={disabled || locked || implied}
                      onChange={() => onToggle(item.key)}
                    />
                    <span>{item.label}</span>
                  </label>
                )
              })}
            </div>
          </fieldset>
        ))}
      </div>
    </div>
  )
}

export default UsersSettings
