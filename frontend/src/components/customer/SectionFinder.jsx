import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { sectionFinderApi } from '../../api/customerClient'
import { useCart } from '../../contexts/CartContext'

const EMPTY = {
  application: 'residential',
  series: '',
  thickness: '',
  gauge: 'standard',
  section_height: '',
  width_feet: '',
  width_inches: '0',
  color: '',
  design: '',
  position: '',
  windows: '',
  end_caps: '',
  quantity: '1',
  notes: '',
}

function Field({ label, children }) {
  return (
    <label className="block text-sm text-gray-700">
      <span className="block text-xs font-medium text-gray-500 mb-1">{label}</span>
      {children}
    </label>
  )
}

const selectClass = 'w-full border border-gray-300 rounded-md px-2 py-2 text-sm bg-white'

export default function SectionFinder() {
  const { addItem } = useCart()
  const [mode, setMode] = useState('loading')
  const [options, setOptions] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [photoName, setPhotoName] = useState('')
  const [photo, setPhoto] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    sectionFinderApi.status()
      .then((response) => {
        setMode(response.data.mode || 'off')
        setOptions(response.data.options)
      })
      .catch(() => setMode('off'))
  }, [])

  const seriesChoices = useMemo(() => {
    const rows = options?.series || []
    return rows.filter((row) => row.application === form.application)
  }, [options, form.application])

  const selectedSeries = seriesChoices.find((row) => row.id === form.series)

  function setField(name, value) {
    setForm((current) => ({ ...current, [name]: value }))
    setResult(null)
    setNotice('')
  }

  function onPhoto(event) {
    const file = event.target.files && event.target.files[0]
    if (!file) {
      setPhoto('')
      setPhotoName('')
      return
    }
    if (file.size > 2 * 1024 * 1024) {
      setError('Photo must be 2 MB or smaller.')
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      setPhoto(String(reader.result || ''))
      setPhotoName(file.name)
      setError('')
    }
    reader.readAsDataURL(file)
  }

  function payload() {
    return {
      application: form.application,
      series: form.series,
      thickness: form.thickness,
      gauge: form.gauge,
      section_height: form.section_height === '' ? null : Number(form.section_height),
      width_feet: form.width_feet === '' ? null : Number(form.width_feet),
      width_inches: form.width_inches === '' ? 0 : Number(form.width_inches),
      color: form.color,
      design: form.design,
      position: form.position,
      windows: form.windows === '' ? null : form.windows === 'yes',
      end_caps: form.end_caps || null,
      quantity: form.quantity === '' ? null : Number(form.quantity),
      notes: form.notes,
      photo: photo || null,
    }
  }

  async function findSection(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const response = await sectionFinderApi.resolve(payload())
      setResult(response.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not look up that section.')
    }
    setBusy(false)
  }

  function addToCart() {
    addItem({
      item_number: result.part_number,
      description: result.description,
      quantity: result.quantity || 1,
      unit_price: result.list_price,
    })
    setNotice('Added to the cart at the list price.')
  }

  async function sendToStaff() {
    setBusy(true)
    setError('')
    try {
      const response = await sectionFinderApi.review(payload())
      if (response.data.status === 'shadow') {
        setNotice('Shadow mode only. This was not sent to staff.')
      } else {
        setNotice('Sent to Open Distribution for review. Nothing was guessed.')
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not send the request.')
    }
    setBusy(false)
  }

  if (mode === 'loading') {
    return <div className="p-8 text-sm text-gray-500">Loading section finder…</div>
  }
  if (mode !== 'on') {
    return (
      <div className="max-w-xl mx-auto p-8">
        <h1 className="text-xl font-semibold text-gray-900">Replacement sections</h1>
        <p className="mt-2 text-sm text-gray-600">This page is turned off.</p>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto p-4 sm:p-6">
      <h1 className="text-2xl font-semibold text-gray-900">Replacement section</h1>
      <p className="mt-1 text-sm text-gray-600">
        Describe the section. A single stocked part is priced at the list price. Anything else goes to Open Distribution. No part number is guessed.
      </p>
      <form onSubmit={findSection} className="mt-6 bg-white border border-gray-200 rounded-lg p-4 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Application">
            <select aria-label="Application" className={selectClass} value={form.application} onChange={(event) => setField('application', event.target.value)}>
              <option value="residential">Residential</option>
              <option value="commercial">Commercial</option>
            </select>
          </Field>
          <Field label="Door series">
            <select aria-label="Door series" className={selectClass} value={form.series} onChange={(event) => {
              const id = event.target.value
              const row = seriesChoices.find((item) => item.id === id)
              setForm((current) => ({
                ...current,
                series: id,
                thickness: row ? row.thickness : '',
                gauge: row ? row.gauge : 'standard',
                section_height: '',
                design: '',
              }))
              setResult(null)
            }}>
              <option value="">Choose</option>
              <option value="not sure">Not sure</option>
              {seriesChoices.map((row) => (
                <option key={row.id} value={row.id}>{row.id}</option>
              ))}
            </select>
          </Field>
          <Field label="Door thickness">
            <select aria-label="Door thickness" className={selectClass} value={form.thickness} onChange={(event) => setField('thickness', event.target.value)}>
              <option value="">Choose</option>
              {(options?.thicknesses || []).map((value) => (
                <option key={value} value={value}>{value} inch</option>
              ))}
            </select>
          </Field>
          <Field label="Gauge">
            <select aria-label="Gauge" className={selectClass} value={form.gauge} onChange={(event) => setField('gauge', event.target.value)}>
              <option value="standard">Standard</option>
              <option value="20">20 gauge</option>
            </select>
          </Field>
          <Field label="Section height">
            <select aria-label="Section height" className={selectClass} value={form.section_height} onChange={(event) => setField('section_height', event.target.value)}>
              <option value="">Choose</option>
              {(selectedSeries?.heights || [21, 24, 28, 32]).map((value) => (
                <option key={value} value={value}>{value} inch</option>
              ))}
            </select>
          </Field>
          <Field label="Door width">
            <span className="flex gap-2">
              <input aria-label="Width feet" type="number" min="1" max="40" className={selectClass} placeholder="Feet" value={form.width_feet} onChange={(event) => setField('width_feet', event.target.value)} />
              <input aria-label="Width inches" type="number" min="0" max="11" className={selectClass} placeholder="Inches" value={form.width_inches} onChange={(event) => setField('width_inches', event.target.value)} />
            </span>
          </Field>
          <Field label="Colour">
            <select aria-label="Colour" className={selectClass} value={form.color} onChange={(event) => setField('color', event.target.value)}>
              <option value="">Choose</option>
              {(options?.colors || []).map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </Field>
          <Field label="Design or texture">
            <select aria-label="Design" className={selectClass} value={form.design} onChange={(event) => setField('design', event.target.value)}>
              <option value="">Choose</option>
              {(selectedSeries?.designs || []).map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </Field>
          <Field label="Position in the door">
            <select aria-label="Position" className={selectClass} value={form.position} onChange={(event) => setField('position', event.target.value)}>
              <option value="">Choose</option>
              <option value="bottom">Bottom</option>
              <option value="intermediate">Intermediate</option>
              <option value="top">Top</option>
            </select>
          </Field>
          {form.series && form.series !== 'not sure' && form.series !== 'KANATA' && form.series !== 'CRAFT' && (
            <Field label="End caps / hinges">
              <select aria-label="End caps" className={selectClass} value={form.end_caps} onChange={(event) => setField('end_caps', event.target.value)}>
                <option value="">Choose</option>
                <option value="single">Single</option>
                <option value="double">Double</option>
                <option value="not sure">Not sure</option>
              </select>
            </Field>
          )}
          <Field label="Windows in this section">
            <select aria-label="Windows" className={selectClass} value={form.windows} onChange={(event) => setField('windows', event.target.value)}>
              <option value="">Choose</option>
              <option value="no">No</option>
              <option value="yes">Yes</option>
            </select>
          </Field>
          <Field label="Quantity">
            <input aria-label="Quantity" type="number" min="1" max="100" className={selectClass} value={form.quantity} onChange={(event) => setField('quantity', event.target.value)} />
          </Field>
        </div>
        <Field label="Notes">
          <textarea aria-label="Notes" maxLength={2000} className={selectClass} rows={3} value={form.notes} onChange={(event) => setField('notes', event.target.value)} />
        </Field>
        <Field label="Photo, optional">
          <input aria-label="Photo" type="file" accept="image/*" onChange={onPhoto} className="text-sm" />
          {photoName && <span className="block mt-1 text-xs text-gray-500">{photoName}</span>}
        </Field>
        <button type="submit" disabled={busy} className="px-4 py-2 rounded-md bg-odc-600 text-white text-sm font-medium disabled:opacity-50">
          {busy ? 'Looking up…' : 'Find section'}
        </button>
      </form>

      {error && <p className="mt-4 text-sm text-red-700">{error}</p>}
      {notice && <p className="mt-4 text-sm text-green-800">{notice}</p>}

      {result?.status === 'resolved' && (
        <div className="mt-4 bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-xs font-medium text-gray-500">One section</p>
          <p className="mt-1 text-lg font-medium text-gray-900">{result.description}</p>
          <p className="mt-1 font-mono text-sm text-gray-700">{result.part_number}</p>
          <p className="mt-2 text-sm text-gray-900">List price ${Number(result.list_price).toFixed(2)} each, quantity {result.quantity}</p>
          {mode === 'on' ? (
            <div className="mt-3 flex gap-3">
              <button type="button" onClick={addToCart} className="px-4 py-2 rounded-md bg-odc-600 text-white text-sm">Add to cart</button>
              <Link to="/cart" className="px-4 py-2 rounded-md border border-gray-300 text-sm">Open cart</Link>
            </div>
          ) : (
            <p className="mt-3 text-sm text-amber-800">Shadow mode does not add this to the cart.</p>
          )}
        </div>
      )}

      {result?.status === 'review' && (
        <div className="mt-4 bg-white border border-amber-200 rounded-lg p-4">
          <p className="text-sm font-medium text-gray-900">This needs a person at Open Distribution.</p>
          <ul className="mt-2 list-disc pl-5 text-sm text-gray-700 space-y-1">
            {(result.reasons || []).map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
          {mode === 'on' ? (
            <button type="button" onClick={sendToStaff} disabled={busy} className="mt-3 px-4 py-2 rounded-md bg-gray-900 text-white text-sm">
              Send to Open Distribution
            </button>
          ) : (
            <p className="mt-3 text-sm text-amber-800">Shadow mode does not send this.</p>
          )}
        </div>
      )}
    </div>
  )
}
