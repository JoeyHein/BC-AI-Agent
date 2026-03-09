import { useState } from 'react';
import { springBuilderApi } from '../../api/customerClient';
import { useCart } from '../../contexts/CartContext';

const WIRE_SIZES = [
  { value: 0.1875, label: '.1875"' },
  { value: 0.192, label: '.192"' },
  { value: 0.207, label: '.207"' },
  { value: 0.218, label: '.218"' },
  { value: 0.225, label: '.225"' },
  { value: 0.234, label: '.234"' },
  { value: 0.243, label: '.243"' },
  { value: 0.250, label: '.250"' },
  { value: 0.262, label: '.262"' },
  { value: 0.273, label: '.273"' },
  { value: 0.283, label: '.283"' },
  { value: 0.295, label: '.295"' },
  { value: 0.306, label: '.306"' },
  { value: 0.312, label: '.312"' },
  { value: 0.319, label: '.319"' },
  { value: 0.331, label: '.331"' },
  { value: 0.343, label: '.343"' },
  { value: 0.362, label: '.362"' },
  { value: 0.375, label: '.375"' },
  { value: 0.393, label: '.393"' },
  { value: 0.406, label: '.406"' },
  { value: 0.421, label: '.421"' },
  { value: 0.437, label: '.437"' },
  { value: 0.453, label: '.453"' },
  { value: 0.469, label: '.469"' },
  { value: 0.500, label: '.500"' },
];

const COIL_SIZES = [
  { value: 1.75, label: '1-3/4"' },
  { value: 2.0, label: '2"' },
  { value: 2.625, label: '2-5/8"' },
  { value: 3.75, label: '3-3/4"' },
  { value: 6.0, label: '6"' },
];

export default function SpringBuilder() {
  const [mode, setMode] = useState('calculate'); // 'calculate' or 'direct'
  const [calcForm, setCalcForm] = useState({
    door_weight: '',
    door_height: '',
    door_width: '',
    track_radius: 15,
    spring_qty: 2,
    target_cycles: 10000,
    coil_diameter: 2.0,
  });
  const [directForm, setDirectForm] = useState({
    wire_diameter: 0.234,
    coil_diameter: 2.0,
    spring_length: '',
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [orderSuccess, setOrderSuccess] = useState(null);
  const [cartAdded, setCartAdded] = useState(false);
  const [selectedSprings, setSelectedSprings] = useState({ lh: true, rh: true });
  const { addItems } = useCart();

  function handleCalcChange(e) {
    const { name, value } = e.target;
    setCalcForm(prev => ({ ...prev, [name]: value }));
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
        track_radius: parseInt(calcForm.track_radius),
        spring_qty: parseInt(calcForm.spring_qty),
        target_cycles: parseInt(calcForm.target_cycles),
        coil_diameter: parseFloat(calcForm.coil_diameter),
      });
      setResult(res.data);
      if (!res.data.success) {
        setError(res.data.error);
      }
    } catch (e) {
      setError(e.response?.data?.detail || 'Calculation failed');
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
    } catch (e) {
      setError(e.response?.data?.detail || 'Lookup failed');
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
        quantity: result?.calculation?.spring_quantity || 2,
        door_weight: calcForm.door_weight ? parseFloat(calcForm.door_weight) : undefined,
        door_height: calcForm.door_height ? parseFloat(calcForm.door_height) : undefined,
        door_width: calcForm.door_width ? parseFloat(calcForm.door_width) : undefined,
        calculation_data: result?.calculation || result?.specs,
      });
      setOrderSuccess('Special order submitted! Check your special orders for updates.');
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to submit special order');
    }
    setSubmitting(false);
  }

  function switchMode(newMode) {
    setMode(newMode);
    setResult(null);
    setError(null);
    setOrderSuccess(null);
  }

  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Spring Builder</h1>
      <p className="text-sm text-gray-600">Calculate spring specifications or look up springs by size.</p>

      {/* Mode Toggle */}
      <div className="flex rounded-lg border overflow-hidden">
        <button
          onClick={() => switchMode('calculate')}
          className={`flex-1 py-3 px-4 text-sm font-medium transition-colors ${
            mode === 'calculate'
              ? 'bg-blue-600 text-white'
              : 'bg-white text-gray-600 hover:bg-gray-50'
          }`}
        >
          Calculate from Door Specs
        </button>
        <button
          onClick={() => switchMode('direct')}
          className={`flex-1 py-3 px-4 text-sm font-medium transition-colors ${
            mode === 'direct'
              ? 'bg-blue-600 text-white'
              : 'bg-white text-gray-600 hover:bg-gray-50'
          }`}
        >
          I Know My Spring Size
        </button>
      </div>

      {/* Calculate from Door Specs Form */}
      {mode === 'calculate' && (
        <form onSubmit={handleCalculate} className="bg-white rounded-lg border p-6 space-y-4">
          <h2 className="text-lg font-semibold text-gray-800">Door Specifications</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Door Weight (lbs)</label>
              <input
                type="number"
                name="door_weight"
                value={calcForm.door_weight}
                onChange={handleCalcChange}
                required
                min="1"
                step="0.1"
                placeholder="e.g. 150"
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Door Height (inches)</label>
              <input
                type="number"
                name="door_height"
                value={calcForm.door_height}
                onChange={handleCalcChange}
                required
                min="60"
                max="384"
                placeholder="e.g. 84"
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Door Width (inches)</label>
              <input
                type="number"
                name="door_width"
                value={calcForm.door_width}
                onChange={handleCalcChange}
                min="36"
                max="480"
                placeholder="e.g. 96"
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Track Radius</label>
              <select
                name="track_radius"
                value={calcForm.track_radius}
                onChange={handleCalcChange}
                className="w-full px-3 py-2 border rounded-lg"
              >
                <option value="12">12"</option>
                <option value="15">15"</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Spring Qty</label>
              <select
                name="spring_qty"
                value={calcForm.spring_qty}
                onChange={handleCalcChange}
                className="w-full px-3 py-2 border rounded-lg"
              >
                <option value="1">1</option>
                <option value="2">2</option>
                <option value="4">4</option>
                <option value="6">6</option>
                <option value="8">8</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Cycle Life</label>
              <select
                name="target_cycles"
                value={calcForm.target_cycles}
                onChange={handleCalcChange}
                className="w-full px-3 py-2 border rounded-lg"
              >
                <option value="10000">10,000</option>
                <option value="15000">15,000</option>
                <option value="25000">25,000</option>
                <option value="50000">50,000</option>
                <option value="100000">100,000</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Coil Diameter</label>
              <select
                name="coil_diameter"
                value={calcForm.coil_diameter}
                onChange={handleCalcChange}
                className="w-full px-3 py-2 border rounded-lg"
              >
                {COIL_SIZES.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
          </div>
          <button
            type="submit"
            disabled={loading || !calcForm.door_weight || !calcForm.door_height}
            className="w-full py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
          >
            {loading ? 'Calculating...' : 'Calculate Spring'}
          </button>
        </form>
      )}

      {/* Direct Entry Form */}
      {mode === 'direct' && (
        <form onSubmit={handleLookup} className="bg-white rounded-lg border p-6 space-y-4">
          <h2 className="text-lg font-semibold text-gray-800">Spring Specifications</h2>
          <p className="text-sm text-gray-500">Enter the spring size you need and we'll find the matching catalog item.</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Wire Size</label>
              <select
                name="wire_diameter"
                value={directForm.wire_diameter}
                onChange={handleDirectChange}
                className="w-full px-3 py-2 border rounded-lg"
              >
                {WIRE_SIZES.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Coil Diameter</label>
              <select
                name="coil_diameter"
                value={directForm.coil_diameter}
                onChange={handleDirectChange}
                className="w-full px-3 py-2 border rounded-lg"
              >
                {COIL_SIZES.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Spring Length (inches, optional)</label>
              <input
                type="number"
                name="spring_length"
                value={directForm.spring_length}
                onChange={handleDirectChange}
                min="1"
                step="0.25"
                placeholder="e.g. 24"
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
          >
            {loading ? 'Looking up...' : 'Find Spring'}
          </button>
        </form>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 text-red-800 p-3 rounded-lg">{error}</div>
      )}

      {/* Success message for special order */}
      {orderSuccess && (
        <div className="bg-green-50 text-green-800 p-3 rounded-lg">{orderSuccess}</div>
      )}

      {/* Results */}
      {result?.success && (
        <div className="space-y-4">
          {/* Calculation Results (only for calculate mode) */}
          {result.calculation && (
            <div className="bg-white rounded-lg border p-6">
              <h2 className="text-lg font-semibold mb-4">Spring Specifications</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Wire Diameter</span>
                  <div className="font-mono font-bold">.{(result.calculation.wire_diameter * 1000).toFixed(0)}"</div>
                </div>
                <div>
                  <span className="text-gray-500">Coil Diameter</span>
                  <div className="font-mono font-bold">{result.calculation.coil_diameter}"</div>
                </div>
                <div>
                  <span className="text-gray-500">Spring Length</span>
                  <div className="font-mono font-bold">{result.calculation.length}"</div>
                </div>
                <div>
                  <span className="text-gray-500">Active Coils</span>
                  <div className="font-mono font-bold">{result.calculation.active_coils}</div>
                </div>
                <div>
                  <span className="text-gray-500">IPPT</span>
                  <div className="font-mono font-bold">{result.calculation.ippt}</div>
                </div>
                <div>
                  <span className="text-gray-500">MIP/Spring</span>
                  <div className="font-mono font-bold">{result.calculation.mip_per_spring}</div>
                </div>
                <div>
                  <span className="text-gray-500">Turns</span>
                  <div className="font-mono font-bold">{result.calculation.turns}</div>
                </div>
                <div>
                  <span className="text-gray-500">Drum</span>
                  <div className="font-mono font-bold">{result.calculation.drum_model}</div>
                </div>
              </div>
            </div>
          )}

          {/* Shaft Fitment Check */}
          {result.shaft_fitment && (
            <div className={`rounded-lg border p-4 ${
              result.shaft_fitment.fits
                ? 'bg-green-50 border-green-200'
                : 'bg-red-50 border-red-200'
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
                    {result.shaft_fitment.fits ? 'Shaft Fitment: OK' : 'Shaft Fitment: May Not Fit'}
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
                  {result.shaft_fitment.note && (
                    <p className="text-xs text-red-500 mt-1 italic">{result.shaft_fitment.note}</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Direct entry specs summary */}
          {result.specs && !result.calculation && (
            <div className="bg-white rounded-lg border p-6">
              <h2 className="text-lg font-semibold mb-4">Lookup Specifications</h2>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Wire Diameter</span>
                  <div className="font-mono font-bold">.{(result.specs.wire_diameter * 1000).toFixed(0)}"</div>
                </div>
                <div>
                  <span className="text-gray-500">Coil Diameter</span>
                  <div className="font-mono font-bold">{result.specs.coil_diameter}"</div>
                </div>
                {result.specs.length && (
                  <div>
                    <span className="text-gray-500">Spring Length</span>
                    <div className="font-mono font-bold">{result.specs.length}"</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* SKU Matches — selectable LH / RH */}
          <div className="bg-white rounded-lg border p-6">
            <h2 className="text-lg font-semibold mb-4">Catalog Match</h2>
            <div className="space-y-3">
              {['lh', 'rh'].map(side => {
                const spring = result.springs?.[side];
                if (!spring) return null;
                const springLen = result.calculation?.length || result.specs?.length;
                return (
                  <label key={side} className={`flex items-center justify-between py-2 border-b last:border-0 cursor-pointer rounded px-2 ${selectedSprings[side] ? 'bg-blue-50' : ''}`}>
                    <div className="flex items-center">
                      <input
                        type="checkbox"
                        checked={selectedSprings[side]}
                        onChange={e => setSelectedSprings(prev => ({ ...prev, [side]: e.target.checked }))}
                        className="h-4 w-4 text-blue-600 rounded mr-3"
                      />
                      <span className="text-xs text-gray-400 uppercase mr-2">{side}</span>
                      <span className="font-mono text-sm font-medium">{spring.part_number}</span>
                      <span className="ml-2 text-sm text-gray-500">{spring.description}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {spring.matched ? (
                        <>
                          <span className="px-2 py-0.5 bg-green-100 text-green-800 text-xs rounded-full">In Stock</span>
                          {spring.price != null && (
                            <span className="font-medium text-sm">${spring.price.toFixed(2)}/in</span>
                          )}
                          {spring.price != null && springLen && (
                            <span className="text-xs text-gray-500">({springLen}" = ${(spring.price * springLen).toFixed(2)})</span>
                          )}
                        </>
                      ) : (
                        <span className="px-2 py-0.5 bg-yellow-100 text-yellow-800 text-xs rounded-full">Special Order</span>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Cone Sets — shown for selected springs */}
          {result.cone_sets && (selectedSprings.lh || selectedSprings.rh) && (
            <div className="bg-white rounded-lg border p-6">
              <h2 className="text-lg font-semibold mb-4">Winder/Stationary Sets</h2>
              <div className="space-y-2">
                {['lh', 'rh'].map(side => {
                  if (!selectedSprings[side]) return null;
                  const cone = result.cone_sets[side];
                  if (!cone) return null;
                  return (
                    <div key={side} className="flex items-center justify-between py-2">
                      <div>
                        <span className="text-xs text-gray-400 uppercase mr-2">{side}</span>
                        <span className="font-mono text-sm">{cone.part_number}</span>
                        <span className="ml-2 text-sm text-gray-500">{cone.description}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Add to Cart */}
          {(result.springs?.lh?.matched || result.springs?.rh?.matched) && (selectedSprings.lh || selectedSprings.rh) && (
            <div>
              {cartAdded ? (
                <div className="bg-green-50 text-green-800 p-3 rounded-lg text-sm text-center">
                  Added to cart!
                </div>
              ) : (
                <button
                  onClick={() => {
                    const cartItems = [];
                    const springLen = result.calculation?.length || result.specs?.length || 1;
                    for (const side of ['lh', 'rh']) {
                      if (!selectedSprings[side]) continue;
                      const spring = result.springs[side];
                      if (!spring?.part_number || !spring.matched) continue;
                      // Springs sold by the inch
                      cartItems.push({
                        item_number: spring.part_number,
                        description: spring.description || `${side.toUpperCase()} Spring`,
                        quantity: springLen,
                        unit_price_estimate: spring.price || null,
                        source: 'spring-builder',
                      });
                      // Matching cone set
                      const cone = result.cone_sets?.[side];
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
                  }}
                  className="w-full py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium"
                >
                  {selectedSprings.lh && selectedSprings.rh
                    ? 'Add Spring Set to Cart'
                    : `Add ${selectedSprings.lh ? 'LH' : 'RH'} Spring to Cart`}
                </button>
              )}
            </div>
          )}

          {/* Special Order Button */}
          {result.special_order_needed && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-sm text-yellow-800 mb-3">
                This spring configuration is not available in our standard catalog.
                Submit a special order request and we'll provide a quote.
              </p>
              <button
                onClick={handleSpecialOrder}
                disabled={submitting}
                className="px-4 py-2 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 disabled:opacity-50"
              >
                {submitting ? 'Submitting...' : 'Submit Special Order'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
