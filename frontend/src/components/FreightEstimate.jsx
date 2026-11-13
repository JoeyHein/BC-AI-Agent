import { useEffect, useState } from 'react'
import { freightEstimatorApi } from '../api/client'

const SERIES = ['TX380', 'TX450', 'TX450-20', 'TX500', 'TX500-20', 'TX760', 'KANATA', 'CRAFT']
const OPERATORS = [
  ['NONE', 'No operator'],
  ['residential_trolley', 'Residential trolley'],
  ['residential_jackshaft', 'Residential jackshaft'],
  ['commercial_trolley', 'Commercial trolley'],
  ['commercial_hoist', 'Commercial hoist'],
  ['commercial_jackshaft', 'Commercial jackshaft'],
  ['chain_hoist', 'Manual chain hoist'],
]

function emptyDoor() {
  return {
    doorSeries: 'TX450',
    widthFeet: 16,
    widthInches: 0,
    heightFeet: 8,
    heightInches: 0,
    doorCount: 1,
    doorType: 'commercial',
    trackThickness: '2',
    trackMount: 'bracket',
    liftType: 'standard',
    operator: 'NONE',
  }
}

function emptySkid() {
  return { label: '', length_in: 48, width_in: 40, height_in: 24, weight_lb: 250 }
}

function cad(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toLocaleString('en-CA', { style: 'currency', currency: 'CAD' })
}

function lb(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Number(value).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} lb`
}

function num(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function doorRequest(door) {
  if (door.doorWidth != null) return door
  return {
    doorSeries: door.doorSeries,
    doorType: door.doorType || 'commercial',
    doorWidth: num(door.widthFeet) * 12 + num(door.widthInches),
    doorHeight: num(door.heightFeet) * 12 + num(door.heightInches),
    doorCount: num(door.doorCount) || 1,
    trackThickness: door.trackThickness,
    trackMount: door.trackMount,
    liftType: door.liftType,
    trackRadius: door.trackRadius || '15',
    operator: door.operator,
  }
}

function describeDoor(door) {
  if (door.doorWidth != null) {
    const widthFeet = Math.floor(door.doorWidth / 12)
    const widthInches = door.doorWidth % 12
    const heightFeet = Math.floor((door.doorHeight || 0) / 12)
    const heightInches = (door.doorHeight || 0) % 12
    return `${door.doorCount || 1} × ${door.doorSeries || 'door'} ${widthFeet}'${widthInches}" × ${heightFeet}'${heightInches}"`
  }
  return `${door.doorCount || 1} × ${door.doorSeries} ${door.widthFeet}'${door.widthInches}" × ${door.heightFeet}'${door.heightInches}"`
}

function ChargeCells({ rating }) {
  if (!rating || rating.rated === false) {
    return <td colSpan={6} className="px-3 py-2 text-sm text-amber-800">{rating?.message || '—'}</td>
  }
  return (
    <>
      <td className="px-3 py-2 text-sm text-gray-700">{rating.break}</td>
      <td className="px-3 py-2 text-sm text-right text-gray-900">{cad(rating.linehaul)}</td>
      <td className="px-3 py-2 text-sm text-right text-gray-900">{cad(rating.long)}</td>
      <td className="px-3 py-2 text-sm text-right text-gray-900">{cad(rating.fuel)}</td>
      <td className="px-3 py-2 text-sm text-right text-gray-900">{cad(rating.gst)}</td>
      <td className="px-3 py-2 text-sm text-right font-medium text-gray-900">{cad(rating.all_in)}</td>
    </>
  )
}

export function FreightEstimatePanel({ doors = null, showOffMessage = false }) {
  const usingConfigurator = Array.isArray(doors)
  const [phase, setPhase] = useState('loading')
  const [meta, setMeta] = useState(null)
  const [origin, setOrigin] = useState('redcliff')
  const [destination, setDestination] = useState('calgary')
  const [fuelPercent, setFuelPercent] = useState('68.80')
  const [manualDoors, setManualDoors] = useState([emptyDoor()])
  const [skids, setSkids] = useState([])
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    freightEstimatorApi.enabled()
      .then((response) => {
        if (cancelled) return
        setMeta(response.data)
        setFuelPercent(String(response.data?.defaults?.fuel_percent ?? '68.80'))
        setPhase('on')
      })
      .catch((err) => {
        if (cancelled) return
        setPhase(err?.response?.status === 404 ? 'off' : 'error')
      })
    return () => { cancelled = true }
  }, [])

  if (phase === 'loading') return null
  if (phase === 'off') {
    if (!showOffMessage) return null
    return (
      <p className="text-sm text-gray-600">Freight estimate is turned off. Turn it on under Settings, General.</p>
    )
  }
  if (phase === 'error') {
    return <p className="text-sm text-red-700">Freight estimate could not be loaded.</p>
  }

  const doorLines = usingConfigurator ? doors : manualDoors
  const origins = meta?.origins || []
  const destinations = meta?.destinations || []

  function updateDoor(index, patch) {
    setManualDoors((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  function updateSkid(index, patch) {
    setSkids((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  async function onEstimate(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const response = await freightEstimatorApi.estimate({
        origin,
        destination,
        fuel_percent: num(fuelPercent),
        doors: doorLines.map(doorRequest),
        skids: skids.map((skid) => ({
          label: skid.label || undefined,
          length_in: num(skid.length_in),
          width_in: num(skid.width_in),
          height_in: num(skid.height_in),
          weight_lb: num(skid.weight_lb),
        })),
      })
      setResult(response.data)
    } catch (err) {
      const detail = err?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'The estimate did not run.')
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  const shipment = result?.shipment
  const aloneTotal = (result?.pieces || []).reduce((sum, piece) => sum + Number(piece.rated_alone?.all_in || 0), 0)
  const totalsDiffer = shipment?.rated && Math.abs(aloneTotal - Number(shipment.all_in || 0)) > 0.02

  return (
    <form onSubmit={onEstimate} className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
      <div>
        <h3 className="text-sm font-medium text-gray-900">Freight estimate</h3>
        <p className="mt-1 text-xs text-gray-500">{meta?.signed_note}</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="block text-sm text-gray-700">
          <span className="block text-xs font-medium text-gray-500 mb-1">Ship from</span>
          <select aria-label="Ship from" value={origin} onChange={(event) => setOrigin(event.target.value)} className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm">
            {origins.map((row) => <option key={row.id} value={row.id}>{row.label}</option>)}
          </select>
        </label>
        <label className="block text-sm text-gray-700">
          <span className="block text-xs font-medium text-gray-500 mb-1">Destination city</span>
          <select aria-label="Destination city" value={destination} onChange={(event) => setDestination(event.target.value)} className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm">
            {destinations.map((row) => <option key={row.id} value={row.id}>{row.label}</option>)}
          </select>
        </label>
        <label className="block text-sm text-gray-700">
          <span className="block text-xs font-medium text-gray-500 mb-1">Fuel % on linehaul</span>
          <input aria-label="Fuel percent" type="number" min="0" step="0.01" value={fuelPercent} onChange={(event) => setFuelPercent(event.target.value)} className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm" />
        </label>
      </div>

      {usingConfigurator ? (
        <div>
          <p className="text-xs font-medium text-gray-500 mb-1">Door lines on this quote</p>
          <ul className="text-sm text-gray-800 space-y-1">
            {doorLines.map((door, index) => <li key={index}>{describeDoor(door)}</li>)}
          </ul>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-gray-500">Door lines</p>
            <button type="button" onClick={() => setManualDoors((rows) => [...rows, emptyDoor()])} className="text-xs font-medium text-odc-700 hover:text-odc-900">Add door</button>
          </div>
          {manualDoors.map((door, index) => (
            <div key={index} className="grid grid-cols-2 md:grid-cols-6 gap-2 border border-gray-100 rounded-md p-2">
              <label className="text-xs text-gray-500">Series
                <select aria-label={`Door ${index + 1} series`} value={door.doorSeries} onChange={(event) => updateDoor(index, { doorSeries: event.target.value })} className="mt-1 w-full border border-gray-300 rounded-md px-2 py-1 text-sm text-gray-900">
                  {SERIES.map((series) => <option key={series}>{series}</option>)}
                </select>
              </label>
              <label className="text-xs text-gray-500">Width ft
                <input aria-label={`Door ${index + 1} width feet`} type="number" min="0" value={door.widthFeet} onChange={(event) => updateDoor(index, { widthFeet: event.target.value })} className="mt-1 w-full border border-gray-300 rounded-md px-2 py-1 text-sm" />
              </label>
              <label className="text-xs text-gray-500">Width in
                <input aria-label={`Door ${index + 1} width inches`} type="number" min="0" max="11" value={door.widthInches} onChange={(event) => updateDoor(index, { widthInches: event.target.value })} className="mt-1 w-full border border-gray-300 rounded-md px-2 py-1 text-sm" />
              </label>
              <label className="text-xs text-gray-500">Height ft
                <input aria-label={`Door ${index + 1} height feet`} type="number" min="0" value={door.heightFeet} onChange={(event) => updateDoor(index, { heightFeet: event.target.value })} className="mt-1 w-full border border-gray-300 rounded-md px-2 py-1 text-sm" />
              </label>
              <label className="text-xs text-gray-500">Height in
                <input aria-label={`Door ${index + 1} height inches`} type="number" min="0" max="11" value={door.heightInches} onChange={(event) => updateDoor(index, { heightInches: event.target.value })} className="mt-1 w-full border border-gray-300 rounded-md px-2 py-1 text-sm" />
              </label>
              <label className="text-xs text-gray-500">Qty
                <input aria-label={`Door ${index + 1} quantity`} type="number" min="1" value={door.doorCount} onChange={(event) => updateDoor(index, { doorCount: event.target.value })} className="mt-1 w-full border border-gray-300 rounded-md px-2 py-1 text-sm" />
              </label>
              <label className="text-xs text-gray-500">Track
                <select aria-label={`Door ${index + 1} track`} value={door.trackThickness} onChange={(event) => updateDoor(index, { trackThickness: event.target.value })} className="mt-1 w-full border border-gray-300 rounded-md px-2 py-1 text-sm">
                  <option value="2">2 in</option>
                  <option value="3">3 in</option>
                </select>
              </label>
              <label className="text-xs text-gray-500">Mount
                <select aria-label={`Door ${index + 1} mount`} value={door.trackMount} onChange={(event) => updateDoor(index, { trackMount: event.target.value })} className="mt-1 w-full border border-gray-300 rounded-md px-2 py-1 text-sm">
                  <option value="bracket">Bracket</option>
                  <option value="angle">Angle</option>
                </select>
              </label>
              <label className="text-xs text-gray-500">Lift
                <select aria-label={`Door ${index + 1} lift`} value={door.liftType} onChange={(event) => updateDoor(index, { liftType: event.target.value })} className="mt-1 w-full border border-gray-300 rounded-md px-2 py-1 text-sm">
                  <option value="standard">Standard</option>
                  <option value="low_headroom">Low headroom</option>
                  <option value="high_lift">High lift</option>
                  <option value="vertical">Vertical</option>
                </select>
              </label>
              <label className="text-xs text-gray-500 col-span-2">Operator
                <select aria-label={`Door ${index + 1} operator`} value={door.operator} onChange={(event) => updateDoor(index, { operator: event.target.value })} className="mt-1 w-full border border-gray-300 rounded-md px-2 py-1 text-sm">
                  {OPERATORS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                </select>
              </label>
              <button type="button" onClick={() => setManualDoors((rows) => rows.filter((_, i) => i !== index))} className="text-xs text-red-700 self-end pb-1">Remove</button>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-gray-500">Manual skids</p>
          <button type="button" onClick={() => setSkids((rows) => [...rows, emptySkid()])} className="text-xs font-medium text-odc-700 hover:text-odc-900">Add skid</button>
        </div>
        {skids.map((skid, index) => (
          <div key={index} className="grid grid-cols-2 md:grid-cols-6 gap-2">
            <input aria-label={`Skid ${index + 1} label`} placeholder="Label" value={skid.label} onChange={(event) => updateSkid(index, { label: event.target.value })} className="border border-gray-300 rounded-md px-2 py-1 text-sm" />
            <input aria-label={`Skid ${index + 1} length`} type="number" min="1" step="0.01" value={skid.length_in} onChange={(event) => updateSkid(index, { length_in: event.target.value })} className="border border-gray-300 rounded-md px-2 py-1 text-sm" title="Length, inches" />
            <input aria-label={`Skid ${index + 1} width`} type="number" min="1" step="0.01" value={skid.width_in} onChange={(event) => updateSkid(index, { width_in: event.target.value })} className="border border-gray-300 rounded-md px-2 py-1 text-sm" title="Width, inches" />
            <input aria-label={`Skid ${index + 1} height`} type="number" min="1" step="0.01" value={skid.height_in} onChange={(event) => updateSkid(index, { height_in: event.target.value })} className="border border-gray-300 rounded-md px-2 py-1 text-sm" title="Height, inches" />
            <input aria-label={`Skid ${index + 1} weight`} type="number" min="0" step="0.01" value={skid.weight_lb} onChange={(event) => updateSkid(index, { weight_lb: event.target.value })} className="border border-gray-300 rounded-md px-2 py-1 text-sm" title="Weight, pounds" />
            <button type="button" onClick={() => setSkids((rows) => rows.filter((_, i) => i !== index))} className="text-xs text-red-700">Remove</button>
          </div>
        ))}
        {skids.length > 0 && <p className="text-xs text-gray-500">Skid size is length × width × height in inches, then weight in pounds. The weight you enter is the ship weight.</p>}
      </div>

      <button type="submit" disabled={busy} className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50">
        {busy ? 'Estimating…' : 'Estimate freight'}
      </button>
      {error && <p className="text-sm text-red-700">{error}</p>}

      {result && (
        <div className="space-y-4">
          {result.rate_table?.notice && (
            <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-md p-2">{result.rate_table.notice}</p>
          )}
          <p className="text-xs text-gray-500">{result.signed_note}</p>

          {result.lines?.length > 0 && (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <caption className="text-left text-xs font-medium text-gray-500 mb-1">Ship weight per door</caption>
                <thead>
                  <tr className="text-left text-xs text-gray-500">
                    <th className="pr-3 py-1 font-medium">Door</th>
                    <th className="pr-3 py-1 font-medium text-right">Hanging</th>
                    <th className="pr-3 py-1 font-medium text-right">Track</th>
                    <th className="pr-3 py-1 font-medium text-right">Springs</th>
                    <th className="pr-3 py-1 font-medium text-right">Shaft</th>
                    <th className="pr-3 py-1 font-medium text-right">Drums</th>
                    <th className="pr-3 py-1 font-medium text-right">Bearings</th>
                    <th className="pr-3 py-1 font-medium text-right">Cones</th>
                    <th className="pr-3 py-1 font-medium text-right">Operator</th>
                    <th className="py-1 font-medium text-right">Each</th>
                  </tr>
                </thead>
                <tbody>
                  {result.lines.map((line) => (
                    <tr key={line.line} className="border-t border-gray-100">
                      <td className="pr-3 py-1 text-gray-900">{line.qty} × {line.label}</td>
                      <td className="pr-3 py-1 text-right">{lb(line.components.hanging_lb)}</td>
                      <td className="pr-3 py-1 text-right">{lb(line.components.track_lb)}</td>
                      <td className="pr-3 py-1 text-right">{lb(line.components.springs_lb)}</td>
                      <td className="pr-3 py-1 text-right">{lb(line.components.shaft_lb)}</td>
                      <td className="pr-3 py-1 text-right">{lb(line.components.drums_lb)}</td>
                      <td className="pr-3 py-1 text-right">{lb(line.components.bearings_lb)}</td>
                      <td className="pr-3 py-1 text-right">{lb(line.components.cones_lb)}</td>
                      <td className="pr-3 py-1 text-right">{lb(line.components.operator_lb)}</td>
                      <td className="py-1 text-right font-medium">{lb(line.product_weight_lb)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <caption className="text-left text-xs font-medium text-gray-500 mb-1">Each crate or skid if it shipped alone</caption>
              <thead>
                <tr className="text-left text-xs text-gray-500">
                  <th className="px-3 py-1 font-medium">Piece</th>
                  <th className="px-3 py-1 font-medium">Dims</th>
                  <th className="px-3 py-1 font-medium text-right">Ship wt</th>
                  <th className="px-3 py-1 font-medium text-right">Cube</th>
                  <th className="px-3 py-1 font-medium text-right">Billed</th>
                  <th className="px-3 py-1 font-medium">Break</th>
                  <th className="px-3 py-1 font-medium text-right">Linehaul</th>
                  <th className="px-3 py-1 font-medium text-right">LONG</th>
                  <th className="px-3 py-1 font-medium text-right">Fuel</th>
                  <th className="px-3 py-1 font-medium text-right">GST</th>
                  <th className="px-3 py-1 font-medium text-right">All-in</th>
                </tr>
              </thead>
              <tbody>
                {result.pieces.map((piece) => (
                  <tr key={piece.piece} className="border-t border-gray-100 align-top">
                    <td className="px-3 py-2 text-gray-900">
                      {piece.label}
                      {piece.warning && <span className="block text-xs text-amber-800">{piece.warning}</span>}
                    </td>
                    <td className="px-3 py-2 text-gray-700 whitespace-nowrap">{piece.length_in} × {piece.width_in} × {piece.height_in} in</td>
                    <td className="px-3 py-2 text-right text-gray-900">{lb(piece.ship_weight_lb)}</td>
                    <td className="px-3 py-2 text-right text-gray-700">{piece.cube_cuft} cu ft</td>
                    <td className="px-3 py-2 text-right text-gray-900">{lb(piece.billed_weight_lb)}</td>
                    <ChargeCells rating={piece.rated_alone} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="border border-gray-200 rounded-md p-3">
            <p className="text-xs font-medium text-gray-500">One shipment, {result.origin?.label} to {result.destination?.label}</p>
            {shipment?.rated ? (
              <dl className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm">
                <div><dt className="text-xs text-gray-500">Ship weight</dt><dd>{lb(shipment.actual_weight_lb)}</dd></div>
                <div><dt className="text-xs text-gray-500">Cube</dt><dd>{shipment.cube_cuft} cu ft</dd></div>
                <div><dt className="text-xs text-gray-500">Billed weight</dt><dd>{lb(shipment.billed_weight_lb)} at {shipment.break}</dd></div>
                <div><dt className="text-xs text-gray-500">Rate</dt><dd>${Number(shipment.rate_per_cwt).toFixed(2)} / CWT</dd></div>
                <div><dt className="text-xs text-gray-500">Linehaul</dt><dd>{cad(shipment.linehaul)}</dd></div>
                <div><dt className="text-xs text-gray-500">LONG</dt><dd>{cad(shipment.long)}</dd></div>
                <div><dt className="text-xs text-gray-500">Fuel</dt><dd>{cad(shipment.fuel)}</dd></div>
                <div><dt className="text-xs text-gray-500">GST</dt><dd>{cad(shipment.gst)}</dd></div>
                <div><dt className="text-xs text-gray-500">All-in</dt><dd className="font-medium">{cad(shipment.all_in)}</dd></div>
              </dl>
            ) : (
              <p className="mt-2 text-sm text-amber-800">{shipment?.message}</p>
            )}
            {totalsDiffer && (
              <p className="mt-2 text-xs text-gray-500">The shipment total is one bill of lading. It is not the sum of the per-piece rates, because the weight break and the minimum apply once.</p>
            )}
            {shipment?.minimum_applied && (
              <p className="mt-2 text-xs text-gray-500">The lane minimum raised the linehaul. Fuel is calculated on that linehaul.</p>
            )}
          </div>
        </div>
      )}
    </form>
  )
}

export default function FreightEstimatePage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Freight estimate</h1>
        <p className="mt-1 text-sm text-gray-600">
          Ship weight and a Manitoulin contract rate from Redcliff, Milton, or Mississauga. This does not write a quote or an order.
        </p>
      </div>
      <FreightEstimatePanel showOffMessage />
    </div>
  )
}
