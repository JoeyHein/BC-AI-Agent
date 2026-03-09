import { useState, useEffect } from 'react';
import { inventoryAgentApi } from '../../api/client';

export default function InventoryDashboard() {
  const [dashboard, setDashboard] = useState(null);
  const [signals, setSignals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState(null);
  const [filter, setFilter] = useState('all');

  useEffect(() => { loadData(); }, [filter]);

  async function loadData() {
    setLoading(true);
    try {
      const [dashRes, sigRes] = await Promise.all([
        inventoryAgentApi.getDashboard(),
        inventoryAgentApi.getSignals({
          acknowledged: false,
          ...(filter !== 'all' ? { signal_type: filter } : {}),
          limit: 100,
        }),
      ]);
      setDashboard(dashRes.data);
      setSignals(sigRes.data.items || []);
    } catch (e) {
      console.error('Failed to load inventory data:', e);
    }
    setLoading(false);
  }

  async function runReview() {
    setRunning(true);
    setMessage(null);
    try {
      const res = await inventoryAgentApi.runReview();
      const s = res.data.stats;
      setMessage({
        type: 'success',
        text: `Review complete! Reviewed ${s.parts_reviewed} parts, created ${s.signals_created} signals (${s.critical_stockouts} critical, ${s.reorder_needed} reorder).`,
      });
      loadData();
    } catch (e) {
      setMessage({ type: 'error', text: `Review failed: ${e.response?.data?.detail || e.message}` });
    }
    setRunning(false);
  }

  async function handleAcknowledge(signalId) {
    try {
      await inventoryAgentApi.acknowledgeSignal(signalId);
      loadData();
    } catch (e) {
      console.error('Failed to acknowledge:', e);
    }
  }

  const severityColor = (severity) => {
    if (severity >= 9) return 'bg-red-100 text-red-800';
    if (severity >= 6) return 'bg-orange-100 text-orange-800';
    return 'bg-yellow-100 text-yellow-800';
  };

  const signalTypeLabel = (type) => {
    switch (type) {
      case 'critical_stockout': return 'Critical Stockout';
      case 'reorder_needed': return 'Reorder Needed';
      case 'demand_signal': return 'Demand Signal';
      default: return type;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900">Inventory Review Agent</h2>
        <button
          onClick={runReview}
          disabled={running}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {running ? 'Running Review...' : 'Run Review'}
        </button>
      </div>

      {message && (
        <div className={`p-3 rounded-lg ${message.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
          {message.text}
        </div>
      )}

      {/* Observation Mode Warning */}
      {dashboard?.observation_mode && (
        <div className="bg-blue-50 border border-blue-200 p-3 rounded-lg text-sm text-blue-800">
          Observation mode active until {dashboard.observe_until ? new Date(dashboard.observe_until).toLocaleDateString() : 'TBD'}. Signals are generated but no automated actions will be taken.
        </div>
      )}

      {/* Dashboard Cards */}
      {dashboard && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-white rounded-lg border p-4">
            <div className="text-sm text-gray-500">Active Signals</div>
            <div className="text-2xl font-bold">{dashboard.total_active_signals}</div>
          </div>
          <div className="bg-white rounded-lg border p-4 border-l-4 border-l-red-500">
            <div className="text-sm text-gray-500">Critical Stockouts</div>
            <div className="text-2xl font-bold text-red-600">{dashboard.critical_stockouts}</div>
          </div>
          <div className="bg-white rounded-lg border p-4 border-l-4 border-l-orange-500">
            <div className="text-sm text-gray-500">Reorder Needed</div>
            <div className="text-2xl font-bold text-orange-600">{dashboard.reorder_needed}</div>
          </div>
          <div className="bg-white rounded-lg border p-4 border-l-4 border-l-yellow-500">
            <div className="text-sm text-gray-500">Demand Signals</div>
            <div className="text-2xl font-bold text-yellow-600">{dashboard.demand_signals}</div>
          </div>
        </div>
      )}

      {/* Filter Tabs */}
      <div className="flex space-x-2">
        {['all', 'critical_stockout', 'reorder_needed', 'demand_signal'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1 text-sm rounded-full ${
              filter === f ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {f === 'all' ? 'All' : signalTypeLabel(f)}
          </button>
        ))}
      </div>

      {/* Signals Table */}
      {loading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : signals.length === 0 ? (
        <div className="text-center py-8 text-gray-500">No active signals. Run a review to generate signals.</div>
      ) : (
        <div className="bg-white rounded-lg border overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Item</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Severity</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-500">Stock</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-500">Daily Demand</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-500">Days Left</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-500">Rec. Qty</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {signals.map(s => (
                <tr key={s.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-sm font-mono">{s.bc_item_number}</td>
                  <td className="px-4 py-2 text-sm">{signalTypeLabel(s.signal_type)}</td>
                  <td className="px-4 py-2 text-sm">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${severityColor(s.severity)}`}>
                      {s.severity}/10
                    </span>
                  </td>
                  <td className="px-4 py-2 text-sm text-right">{s.current_stock?.toFixed(0) ?? '-'}</td>
                  <td className="px-4 py-2 text-sm text-right">{s.avg_daily_demand?.toFixed(2) ?? '-'}</td>
                  <td className="px-4 py-2 text-sm text-right">{s.days_of_stock?.toFixed(0) ?? '-'}</td>
                  <td className="px-4 py-2 text-sm text-right font-medium">{s.recommended_qty?.toFixed(0) ?? '-'}</td>
                  <td className="px-4 py-2 text-sm">
                    <button
                      onClick={() => handleAcknowledge(s.id)}
                      className="px-2 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700"
                    >
                      Ack
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
