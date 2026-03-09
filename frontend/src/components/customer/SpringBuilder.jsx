import { useState } from 'react';
import { springBuilderApi } from '../../api/customerClient';

export default function SpringBuilder() {
  const [form, setForm] = useState({
    door_weight: '',
    door_height: '',
    track_radius: 15,
    spring_qty: 2,
    target_cycles: 10000,
    coil_diameter: 2.0,
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [orderSuccess, setOrderSuccess] = useState(null);

  function handleChange(e) {
    const { name, value } = e.target;
    setForm(prev => ({ ...prev, [name]: value }));
  }

  async function handleCalculate(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    setOrderSuccess(null);
    try {
      const res = await springBuilderApi.calculate({
        door_weight: parseFloat(form.door_weight),
        door_height: parseInt(form.door_height),
        track_radius: parseInt(form.track_radius),
        spring_qty: parseInt(form.spring_qty),
        target_cycles: parseInt(form.target_cycles),
        coil_diameter: parseFloat(form.coil_diameter),
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

  async function handleSpecialOrder() {
    if (!result?.calculation) return;
    setSubmitting(true);
    try {
      const calc = result.calculation;
      await springBuilderApi.submitSpecialOrder({
        wire_diameter: calc.wire_diameter,
        coil_diameter: calc.coil_diameter,
        spring_length: calc.length,
        wind_direction: 'LH',
        quantity: calc.spring_quantity,
        door_weight: parseFloat(form.door_weight),
        door_height: parseFloat(form.door_height),
        calculation_data: calc,
      });
      setOrderSuccess('Special order submitted! Check your special orders for updates.');
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to submit special order');
    }
    setSubmitting(false);
  }

  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Spring Builder</h1>
      <p className="text-sm text-gray-600">Calculate spring specifications and find matching catalog SKUs.</p>

      {/* Calculator Form */}
      <form onSubmit={handleCalculate} className="bg-white rounded-lg border p-6 space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Door Weight (lbs)</label>
            <input
              type="number"
              name="door_weight"
              value={form.door_weight}
              onChange={handleChange}
              required
              min="1"
              step="0.1"
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Door Height (inches)</label>
            <input
              type="number"
              name="door_height"
              value={form.door_height}
              onChange={handleChange}
              required
              min="60"
              max="384"
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Track Radius</label>
            <select
              name="track_radius"
              value={form.track_radius}
              onChange={handleChange}
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
              value={form.spring_qty}
              onChange={handleChange}
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
              value={form.target_cycles}
              onChange={handleChange}
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
              value={form.coil_diameter}
              onChange={handleChange}
              className="w-full px-3 py-2 border rounded-lg"
            >
              <option value="2.0">2"</option>
              <option value="2.625">2-5/8"</option>
              <option value="3.75">3-3/4"</option>
              <option value="6.0">6"</option>
            </select>
          </div>
        </div>
        <button
          type="submit"
          disabled={loading || !form.door_weight || !form.door_height}
          className="w-full py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
        >
          {loading ? 'Calculating...' : 'Calculate Spring'}
        </button>
      </form>

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
          {/* Calculation Results */}
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

          {/* SKU Matches */}
          <div className="bg-white rounded-lg border p-6">
            <h2 className="text-lg font-semibold mb-4">Catalog Match</h2>
            <div className="space-y-3">
              {['lh', 'rh'].map(side => {
                const spring = result.springs?.[side];
                if (!spring) return null;
                return (
                  <div key={side} className="flex items-center justify-between py-2 border-b last:border-0">
                    <div>
                      <span className="font-mono text-sm font-medium">{spring.part_number}</span>
                      <span className="ml-2 text-sm text-gray-500">{spring.description}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {spring.matched ? (
                        <>
                          <span className="px-2 py-0.5 bg-green-100 text-green-800 text-xs rounded-full">In Stock</span>
                          {spring.price && <span className="font-medium">${spring.price.toFixed(2)}</span>}
                        </>
                      ) : (
                        <span className="px-2 py-0.5 bg-yellow-100 text-yellow-800 text-xs rounded-full">Special Order</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Cone Sets */}
          {result.cone_sets && (
            <div className="bg-white rounded-lg border p-6">
              <h2 className="text-lg font-semibold mb-4">Winder/Stationary Sets</h2>
              <div className="space-y-2">
                {['lh', 'rh'].map(side => {
                  const cone = result.cone_sets[side];
                  if (!cone) return null;
                  return (
                    <div key={side} className="flex items-center justify-between py-2">
                      <div>
                        <span className="font-mono text-sm">{cone.part_number}</span>
                        <span className="ml-2 text-sm text-gray-500">{cone.description}</span>
                      </div>
                      <span className="text-xs text-gray-400 uppercase">{side}</span>
                    </div>
                  );
                })}
              </div>
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
