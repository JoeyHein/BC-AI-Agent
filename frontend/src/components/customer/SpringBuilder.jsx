import { useState, useEffect, useCallback } from 'react';
import { springBuilderApi } from '../../api/customerClient';
import { useCart } from '../../contexts/CartContext';

// ============================================================================
// Constants
// ============================================================================

const WIRE_SIZES = [
  { value: 0.1480, label: '.148' }, { value: 0.1563, label: '.156' },
  { value: 0.1620, label: '.162' }, { value: 0.1770, label: '.177' },
  { value: 0.1875, label: '.1875' }, { value: 0.1920, label: '.192' },
  { value: 0.2070, label: '.207' }, { value: 0.2180, label: '.218' },
  { value: 0.2253, label: '.225' }, { value: 0.2343, label: '.234' },
  { value: 0.2437, label: '.2437' }, { value: 0.2500, label: '.250' },
  { value: 0.2625, label: '.2625' }, { value: 0.2730, label: '.273' },
  { value: 0.2830, label: '.283' }, { value: 0.2950, label: '.295' },
  { value: 0.3065, label: '.3065' }, { value: 0.3125, label: '.3125' },
  { value: 0.3190, label: '.319' }, { value: 0.3310, label: '.331' },
  { value: 0.3437, label: '.3437' }, { value: 0.3620, label: '.362' },
  { value: 0.3750, label: '.375' }, { value: 0.3930, label: '.393' },
  { value: 0.4063, label: '.4063' }, { value: 0.4218, label: '.4218' },
  { value: 0.4375, label: '.4375' }, { value: 0.4530, label: '.453' },
  { value: 0.4688, label: '.4688' }, { value: 0.5000, label: '.500' },
];

const COIL_SIZES = [
  { value: 1.75, label: '1 3/4"', shortLabel: '1-3/4' },
  { value: 2.0, label: '2"', shortLabel: '2' },
  { value: 2.625, label: '2 5/8"', shortLabel: '2-5/8' },
  { value: 3.75, label: '3 3/4"', shortLabel: '3-3/4' },
  { value: 6.0, label: '6"', shortLabel: '6' },
];

const LIFT_TYPES = [
  { value: 'standard_15', label: 'Standard (15" radius)' },
  { value: 'standard_12', label: 'Standard (12" radius)' },
  { value: 'high_lift', label: 'High-Lift' },
  { value: 'vertical', label: 'Vertical Lift' },
  { value: 'low_headroom', label: 'Low Headroom' },
];

const CYCLE_OPTIONS = [
  { value: 10000, label: '10,000' },
  { value: 15000, label: '15,000' },
  { value: 25000, label: '25,000' },
  { value: 50000, label: '50,000' },
  { value: 100000, label: '100,000' },
];

const TABS = [
  { id: 'engineering', label: 'Spring Engineering' },
  { id: 'direct', label: 'Buy by Spring Size' },
];

// ============================================================================
// Helpers
// ============================================================================

function inchesToFtIn(totalInches) {
  const n = parseInt(totalInches) || 0;
  const ft = Math.floor(n / 12);
  const inches = n % 12;
  return `${ft}'${inches}"`;
}

function formatWire(wire) {
  if (!wire) return '—';
  return '.' + wire.toFixed(4).replace(/^0\./, '').replace(/0+$/, '');
}

function coilLabel(val) {
  const match = COIL_SIZES.find(c => Math.abs(c.value - val) < 0.01);
  return match ? match.shortLabel : `${val}`;
}

// ============================================================================
// Sub-components
// ============================================================================

function FieldGroup({ label, children, className = '' }) {
  return (
    <div className={className}>
      <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">{label}</label>
      {children}
    </div>
  );
}

function ResultRow({ label, value, unit = '' }) {
  return (
    <div className="flex justify-between items-center py-1.5 border-b border-gray-100 last:border-0">
      <span className="text-sm text-gray-600">{label}</span>
      <span className="font-mono text-sm font-semibold text-gray-900">
        {value}{unit && <span className="text-gray-400 ml-0.5">{unit}</span>}
      </span>
    </div>
  );
}

function Panel({ title, children, className = '' }) {
  return (
    <div className={`bg-white border border-gray-200 rounded-lg ${className}`}>
      {title && (
        <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-200 rounded-t-lg">
          <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wide">{title}</h3>
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
}

function CatalogItem({ spring, side, springLength, selected, onToggle }) {
  if (!spring) return null;
  const total = spring.price && springLength ? (spring.price * springLength).toFixed(2) : null;
  return (
    <label className={`flex items-center justify-between p-3 rounded-lg border cursor-pointer transition-colors ${
      selected ? 'bg-blue-50 border-blue-300' : 'bg-white border-gray-200 hover:border-gray-300'
    }`}>
      <div className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          className="h-4 w-4 text-blue-600 rounded"
        />
        <div>
          <span className="text-xs font-bold text-gray-400 uppercase mr-2">{side}</span>
          <span className="font-mono text-sm font-semibold">{spring.part_number}</span>
          {spring.description && (
            <span className="ml-2 text-xs text-gray-500">{spring.description}</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {spring.matched ? (
          <>
            <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs font-semibold rounded-full">In Stock</span>
            {spring.price != null && (
              <span className="text-sm font-mono font-semibold">${spring.price.toFixed(2)}/in</span>
            )}
            {total && (
              <span className="text-xs text-gray-400">({springLength}" = ${total})</span>
            )}
          </>
        ) : (
          <span className="px-2 py-0.5 bg-amber-100 text-amber-700 text-xs font-semibold rounded-full">Special Order</span>
        )}
      </div>
    </label>
  );
}

// ============================================================================
// Main Component
// ============================================================================

export default function SpringBuilder() {
  const [activeTab, setActiveTab] = useState('engineering');

  // Engineering form state
  const [calcForm, setCalcForm] = useState({
    door_weight: '',
    door_height: '',
    door_width: '',
    lift_type: 'standard_15',
    assembly: 'standard',
    drum_model: '',
    high_lift_inches: 0,
    spring_qty: 2,
    target_cycles: 15000,
    coil_diameter: 2.0,
  });
  const [availableDrums, setAvailableDrums] = useState([]);

  // Direct buy form state
  const [directForm, setDirectForm] = useState({
    wire_diameter: 0.2180,
    coil_diameter: 2.0,
    spring_length: '',
    quantity: 2,
  });

  // Shared state
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [orderSuccess, setOrderSuccess] = useState(null);
  const [cartAdded, setCartAdded] = useState(false);
  const [selectedSprings, setSelectedSprings] = useState({ lh: true, rh: true });
  const { addItems } = useCart();

  // Fetch drums when lift type changes
  useEffect(() => {
    springBuilderApi.getDrums(calcForm.lift_type)
      .then(res => {
        const drums = res.data || [];
        setAvailableDrums(drums);
        if (drums.length > 0 && !drums.includes(calcForm.drum_model)) {
          setCalcForm(prev => ({ ...prev, drum_model: drums[0] }));
        }
      })
      .catch(() => setAvailableDrums([]));
  }, [calcForm.lift_type]);

  // ---- Handlers ----

  function handleCalcChange(e) {
    const { name, value } = e.target;
    if (name === 'lift_type') {
      setCalcForm(prev => ({ ...prev, lift_type: value, drum_model: '' }));
    } else if (name === 'assembly') {
      setCalcForm(prev => ({
        ...prev,
        assembly: value,
        spring_qty: value === 'single' ? 1 : 2,
      }));
    } else {
      setCalcForm(prev => ({ ...prev, [name]: value }));
    }
  }

  function handleDirectChange(e) {
    const { name, value } = e.target;
    setDirectForm(prev => ({ ...prev, [name]: value }));
  }

  async function handleCalculate(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    setOrderSuccess(null);
    setSelectedSprings({ lh: true, rh: true });
    setCartAdded(false);
    try {
      const res = await springBuilderApi.calculate({
        door_weight: parseFloat(calcForm.door_weight),
        door_height: parseInt(calcForm.door_height),
        door_width: calcForm.door_width ? parseFloat(calcForm.door_width) : undefined,
        spring_qty: parseInt(calcForm.spring_qty),
        target_cycles: parseInt(calcForm.target_cycles),
        coil_diameter: parseFloat(calcForm.coil_diameter),
        lift_type: calcForm.lift_type,
        assembly: calcForm.assembly,
        drum_model: calcForm.drum_model,
        high_lift_inches: calcForm.lift_type === 'high_lift' ? parseInt(calcForm.high_lift_inches) || 0 : 0,
      });
      setResult(res.data);
      if (!res.data.success) {
        setError(res.data.error);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Calculation failed');
    }
    setLoading(false);
  }

  async function handleLookup(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    setOrderSuccess(null);
    setSelectedSprings({ lh: true, rh: true });
    setCartAdded(false);
    try {
      const res = await springBuilderApi.lookup({
        wire_diameter: parseFloat(directForm.wire_diameter),
        coil_diameter: parseFloat(directForm.coil_diameter),
        spring_length: directForm.spring_length ? parseFloat(directForm.spring_length) : undefined,
      });
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Lookup failed');
    }
    setLoading(false);
  }

  async function handleSpecialOrder() {
    const specs = result?.calculation || result?.specs;
    if (!specs) return;
    setSubmitting(true);
    try {
      await springBuilderApi.submitSpecialOrder({
        wire_diameter: specs.wire_diameter,
        coil_diameter: specs.coil_diameter,
        spring_length: specs.length || parseFloat(directForm.spring_length) || 0,
        wind_direction: 'LH',
        quantity: result?.calculation?.spring_quantity || parseInt(directForm.quantity) || 2,
        door_weight: calcForm.door_weight ? parseFloat(calcForm.door_weight) : undefined,
        door_height: calcForm.door_height ? parseFloat(calcForm.door_height) : undefined,
        door_width: calcForm.door_width ? parseFloat(calcForm.door_width) : undefined,
        calculation_data: result?.calculation || result?.specs,
      });
      setOrderSuccess('Special order submitted successfully! We will follow up with pricing.');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to submit special order');
    }
    setSubmitting(false);
  }

  const handleAddToCart = useCallback(() => {
    const cartItems = [];
    const springLen = result?.calculation?.length || result?.specs?.length || parseFloat(directForm.spring_length) || 1;
    for (const side of ['lh', 'rh']) {
      if (!selectedSprings[side]) continue;
      const spring = result?.springs?.[side];
      if (!spring?.part_number || !spring.matched) continue;
      cartItems.push({
        item_number: spring.part_number,
        description: spring.description || `${side.toUpperCase()} Spring`,
        quantity: springLen,
        unit_price_estimate: spring.price || null,
        source: 'spring-builder',
      });
      const cone = result?.cone_sets?.[side];
      if (cone?.part_number) {
        cartItems.push({
          item_number: cone.part_number,
          description: cone.description || `${side.toUpperCase()} Cone Set`,
          quantity: 1,
          unit_price_estimate: null,
          source: 'spring-builder',
        });
      }
    }
    if (cartItems.length > 0) {
      addItems(cartItems);
      setCartAdded(true);
      setTimeout(() => setCartAdded(false), 3000);
    }
  }, [result, selectedSprings, directForm.spring_length, addItems]);

  function handleClear() {
    setResult(null);
    setError(null);
    setOrderSuccess(null);
    setCartAdded(false);
  }

  function switchTab(tab) {
    setActiveTab(tab);
    handleClear();
  }

  // ---- Derived values ----
  const calc = result?.calculation;
  const specs = result?.specs;
  const hasResult = result?.success;
  const springLen = calc?.length || specs?.length || parseFloat(directForm.spring_length) || null;
  const canAddToCart = hasResult && (
    (selectedSprings.lh && result?.springs?.lh?.matched) ||
    (selectedSprings.rh && result?.springs?.rh?.matched)
  );

  // ============================================================================
  // RENDER
  // ============================================================================

  return (
    <div className="max-w-6xl mx-auto p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Spring Builder</h1>
          <p className="text-sm text-gray-500 mt-0.5">Calculate torsion springs or buy by spring size</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => switchTab(tab.id)}
            className={`px-5 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ================================================================== */}
      {/* TAB: Spring Engineering */}
      {/* ================================================================== */}
      {activeTab === 'engineering' && (
        <form onSubmit={handleCalculate}>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

            {/* LEFT — Assembly Configuration */}
            <Panel title="Assembly Configuration" className="lg:col-span-1">
              <div className="space-y-3">
                <FieldGroup label="Assembly">
                  <select name="assembly" value={calcForm.assembly} onChange={handleCalcChange}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    <option value="standard">Standard (2 springs)</option>
                    <option value="single">Single Spring</option>
                  </select>
                </FieldGroup>

                <FieldGroup label="I.D. (Coil Diameter)">
                  <select name="coil_diameter" value={calcForm.coil_diameter} onChange={handleCalcChange}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    {COIL_SIZES.map(s => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </FieldGroup>

                <FieldGroup label="Lift Type">
                  <select name="lift_type" value={calcForm.lift_type} onChange={handleCalcChange}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    {LIFT_TYPES.map(lt => (
                      <option key={lt.value} value={lt.value}>{lt.label}</option>
                    ))}
                  </select>
                </FieldGroup>

                <FieldGroup label="Drum">
                  <select name="drum_model" value={calcForm.drum_model} onChange={handleCalcChange} required
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    {availableDrums.length === 0 && <option value="">Loading...</option>}
                    {availableDrums.map(d => <option key={d} value={d}>{d}</option>)}
                  </select>
                </FieldGroup>

                <div className="grid grid-cols-2 gap-3">
                  <FieldGroup label="Radius">
                    <div className="px-3 py-2 border border-gray-200 rounded-md bg-gray-50 text-sm font-mono">
                      {calcForm.lift_type === 'standard_12' || calcForm.lift_type === 'low_headroom' ? '12"' : '15"'}
                    </div>
                  </FieldGroup>
                  <FieldGroup label="Cycles">
                    <select name="target_cycles" value={calcForm.target_cycles} onChange={handleCalcChange}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                      {CYCLE_OPTIONS.map(c => (
                        <option key={c.value} value={c.value}>{c.label}</option>
                      ))}
                    </select>
                  </FieldGroup>
                </div>

                <FieldGroup label={`Springs on door: ${calcForm.spring_qty}`}>
                  <input
                    type="range"
                    name="spring_qty"
                    min="1" max="8" step="1"
                    value={calcForm.spring_qty}
                    onChange={handleCalcChange}
                    className="w-full accent-blue-600"
                  />
                  <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                    <span>1</span><span>2</span><span>4</span><span>6</span><span>8</span>
                  </div>
                </FieldGroup>

                {calcForm.lift_type === 'high_lift' && (
                  <FieldGroup label="High-Lift (inches)">
                    <input type="number" name="high_lift_inches" value={calcForm.high_lift_inches} onChange={handleCalcChange}
                      min="0" max="240" placeholder="e.g. 24"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
                  </FieldGroup>
                )}
              </div>
            </Panel>

            {/* CENTER — Door Information */}
            <Panel title="Door Information" className="lg:col-span-1">
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <FieldGroup label="Width (inches)">
                    <input type="number" name="door_width" value={calcForm.door_width} onChange={handleCalcChange}
                      min="36" max="480" placeholder="e.g. 108"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
                  </FieldGroup>
                  <FieldGroup label="Height (inches)">
                    <input type="number" name="door_height" value={calcForm.door_height} onChange={handleCalcChange}
                      required min="60" max="384" placeholder="e.g. 84"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
                  </FieldGroup>
                </div>

                {/* Ft/In display */}
                {(calcForm.door_width || calcForm.door_height) && (
                  <div className="flex gap-4 text-xs text-gray-400 -mt-1">
                    {calcForm.door_width && <span>W: {inchesToFtIn(calcForm.door_width)}</span>}
                    {calcForm.door_height && <span>H: {inchesToFtIn(calcForm.door_height)}</span>}
                  </div>
                )}

                <FieldGroup label="Door Weight (lbs)">
                  <input type="number" name="door_weight" value={calcForm.door_weight} onChange={handleCalcChange}
                    required min="1" step="0.1" placeholder="e.g. 150"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
                </FieldGroup>

                {/* Visual weight helper */}
                <div className="bg-blue-50 rounded-lg p-3 mt-2">
                  <p className="text-xs text-blue-700">
                    <strong>Tip:</strong> If you don't know the door weight, weigh the door by disconnecting springs and using a scale, or calculate from panel/hardware specs.
                  </p>
                </div>
              </div>

              {/* Calculate button */}
              <div className="mt-4 flex gap-2">
                <button
                  type="submit"
                  disabled={loading || !calcForm.door_weight || !calcForm.door_height || !calcForm.drum_model}
                  className="flex-1 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-semibold text-sm transition-colors"
                >
                  {loading ? (
                    <span className="flex items-center justify-center gap-2">
                      <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                      Calculating...
                    </span>
                  ) : 'Calculate'}
                </button>
                <button type="button" onClick={handleClear}
                  className="px-4 py-2.5 bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 text-sm font-medium transition-colors">
                  Clear
                </button>
              </div>
            </Panel>

            {/* RIGHT — Results */}
            <Panel title="Results" className="lg:col-span-1">
              {!hasResult && !error && (
                <div className="text-center py-8 text-gray-400 text-sm">
                  Enter door specs and click Calculate
                </div>
              )}

              {hasResult && calc && (
                <div className="space-y-4">
                  {/* Single Assembly results */}
                  <div>
                    <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-2">Single Assembly</h4>
                    <div className="bg-gray-50 rounded-lg p-3">
                      <ResultRow label="Turns" value={calc.turns} />
                      <ResultRow label="TIPPT" value={calc.ippt} />
                      <ResultRow label="MIP/Spring" value={calc.mip_per_spring} />
                      <ResultRow label="Cycles" value={calc.cycle_life?.toLocaleString()} />
                      <ResultRow label="Drum" value={calc.drum_model} />
                    </div>
                  </div>

                  {/* Spring specs */}
                  <div>
                    <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-2">Spring</h4>
                    <div className="bg-gray-50 rounded-lg p-3">
                      <ResultRow label="Wire" value={formatWire(calc.wire_diameter)} unit='"' />
                      <ResultRow label="I.D." value={coilLabel(calc.coil_diameter)} unit='"' />
                      <ResultRow label="Length" value={calc.length} unit='"' />
                      <ResultRow label="Qty" value={calc.spring_quantity} />
                      {calc.cable_length && <ResultRow label="Cable Length" value={calc.cable_length} unit='"' />}
                    </div>
                  </div>
                </div>
              )}
            </Panel>
          </div>
        </form>
      )}

      {/* ================================================================== */}
      {/* TAB: Buy by Spring Size (Direct Entry) */}
      {/* ================================================================== */}
      {activeTab === 'direct' && (
        <form onSubmit={handleLookup}>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

            <Panel title="Your Spring Specifications" className="lg:col-span-2">
              <p className="text-sm text-gray-500 mb-4">
                Enter the spring details from your existing spring or the specs you need. We'll find the matching catalog item and cone sets.
              </p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <FieldGroup label="Wire Size">
                  <select name="wire_diameter" value={directForm.wire_diameter} onChange={handleDirectChange}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    {WIRE_SIZES.map(s => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </FieldGroup>

                <FieldGroup label="I.D. (Coil Diameter)">
                  <select name="coil_diameter" value={directForm.coil_diameter} onChange={handleDirectChange}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    {COIL_SIZES.map(s => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </FieldGroup>

                <FieldGroup label="Length (inches)">
                  <input type="number" name="spring_length" value={directForm.spring_length} onChange={handleDirectChange}
                    min="1" step="0.25" placeholder="e.g. 24"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
                </FieldGroup>

                <FieldGroup label="Quantity (springs)">
                  <select name="quantity" value={directForm.quantity} onChange={handleDirectChange}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                    <option value="1">1 (single)</option>
                    <option value="2">2 (pair)</option>
                    <option value="4">4</option>
                    <option value="6">6</option>
                  </select>
                </FieldGroup>
              </div>

              <div className="mt-4 flex gap-2">
                <button type="submit" disabled={loading}
                  className="flex-1 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-semibold text-sm transition-colors">
                  {loading ? 'Looking up...' : 'Find Spring & Cones'}
                </button>
                <button type="button" onClick={handleClear}
                  className="px-4 py-2.5 bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 text-sm font-medium transition-colors">
                  Clear
                </button>
              </div>
            </Panel>

            {/* Quick reference */}
            <Panel title="How It Works" className="lg:col-span-1">
              <div className="space-y-3 text-sm text-gray-600">
                <div className="flex gap-2">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold">1</span>
                  <span>Enter your spring wire size and I.D.</span>
                </div>
                <div className="flex gap-2">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold">2</span>
                  <span>We match it to our catalog and find the right cone sets</span>
                </div>
                <div className="flex gap-2">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold">3</span>
                  <span>Add springs + cones to your cart in one click</span>
                </div>
                <div className="mt-3 p-3 bg-amber-50 rounded-lg text-xs text-amber-700">
                  <strong>Note:</strong> Springs are sold by the inch. Enter the length you need and the total price will be calculated automatically.
                </div>
              </div>
            </Panel>
          </div>
        </form>
      )}

      {/* ================================================================== */}
      {/* Error Display */}
      {/* ================================================================== */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg flex items-start gap-3">
          <svg className="h-5 w-5 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="text-sm">{error}</span>
        </div>
      )}

      {/* Success message */}
      {orderSuccess && (
        <div className="bg-green-50 border border-green-200 text-green-700 p-4 rounded-lg text-sm">{orderSuccess}</div>
      )}

      {/* ================================================================== */}
      {/* Shaft Fitment */}
      {/* ================================================================== */}
      {hasResult && result.shaft_fitment && (
        <div className={`rounded-lg border p-4 ${
          result.shaft_fitment.fits ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'
        }`}>
          <div className="flex items-start gap-3">
            <div className={`mt-0.5 ${result.shaft_fitment.fits ? 'text-green-600' : 'text-red-600'}`}>
              {result.shaft_fitment.fits ? (
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
              )}
            </div>
            <div className="flex-1">
              <h3 className={`text-sm font-semibold ${result.shaft_fitment.fits ? 'text-green-800' : 'text-red-800'}`}>
                Shaft Fitment: {result.shaft_fitment.fits ? 'OK' : 'May Not Fit'}
              </h3>
              <p className={`text-sm mt-1 ${result.shaft_fitment.fits ? 'text-green-700' : 'text-red-700'}`}>
                Required: {result.shaft_fitment.required_width}" / Available: {result.shaft_fitment.door_width}"
                {' '}({result.shaft_fitment.margin > 0 ? '+' : ''}{result.shaft_fitment.margin}" margin)
              </p>
              <details className="mt-2">
                <summary className={`text-xs cursor-pointer ${result.shaft_fitment.fits ? 'text-green-600' : 'text-red-600'}`}>
                  Component breakdown
                </summary>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2 text-xs">
                  {Object.entries(result.shaft_fitment.breakdown).map(([key, val]) => (
                    <div key={key}>
                      <span className="text-gray-500">{key.replace(/_/g, ' ')}</span>
                      <div className="font-mono">{val}"</div>
                    </div>
                  ))}
                </div>
              </details>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================== */}
      {/* Catalog Matches + Cone Sets + Add to Cart */}
      {/* ================================================================== */}
      {hasResult && (result.springs?.lh || result.springs?.rh) && (
        <div className="space-y-4">
          {/* Spring SKUs */}
          <Panel title="Catalog Match">
            <div className="space-y-2">
              {['lh', 'rh'].map(side => (
                <CatalogItem
                  key={side}
                  spring={result.springs?.[side]}
                  side={side === 'lh' ? 'Left Hand' : 'Right Hand'}
                  springLength={springLen}
                  selected={selectedSprings[side]}
                  onToggle={() => setSelectedSprings(prev => ({ ...prev, [side]: !prev[side] }))}
                />
              ))}
            </div>
          </Panel>

          {/* Cone Sets */}
          {result.cone_sets && (selectedSprings.lh || selectedSprings.rh) && (
            <Panel title="Winder / Stationary Cone Sets">
              <div className="space-y-2">
                {['lh', 'rh'].map(side => {
                  if (!selectedSprings[side]) return null;
                  const cone = result.cone_sets[side];
                  if (!cone) return null;
                  return (
                    <div key={side} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                      <div>
                        <span className="text-xs font-bold text-gray-400 uppercase mr-2">{side === 'lh' ? 'Left Hand' : 'Right Hand'}</span>
                        <span className="font-mono text-sm font-semibold">{cone.part_number}</span>
                        {cone.description && (
                          <span className="ml-2 text-xs text-gray-500">{cone.description}</span>
                        )}
                      </div>
                      <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs font-semibold rounded-full">Included</span>
                    </div>
                  );
                })}
              </div>
            </Panel>
          )}

          {/* Add to Cart / Special Order */}
          <div className="flex gap-3">
            {canAddToCart && (
              <button
                onClick={handleAddToCart}
                disabled={cartAdded}
                className={`flex-1 py-3 rounded-lg font-semibold text-sm transition-colors ${
                  cartAdded
                    ? 'bg-green-100 text-green-700'
                    : 'bg-green-600 text-white hover:bg-green-700'
                }`}
              >
                {cartAdded ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    Added to Cart!
                  </span>
                ) : (
                  selectedSprings.lh && selectedSprings.rh
                    ? 'Add Spring Set + Cones to Cart'
                    : `Add ${selectedSprings.lh ? 'LH' : 'RH'} Spring + Cones to Cart`
                )}
              </button>
            )}

            {result.special_order_needed && (
              <button
                onClick={handleSpecialOrder}
                disabled={submitting}
                className="flex-1 py-3 bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-50 font-semibold text-sm transition-colors"
              >
                {submitting ? 'Submitting...' : 'Request Special Order'}
              </button>
            )}
          </div>

          {result.special_order_needed && (
            <p className="text-xs text-amber-600">
              This spring is not in our standard catalog. Submit a special order and we'll follow up with pricing and lead time.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
