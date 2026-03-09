import { useState, useEffect } from 'react';
import { springBuilderApi } from '../../api/customerClient';

export default function SpecialOrders() {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadOrders(); }, []);

  async function loadOrders() {
    try {
      const res = await springBuilderApi.getSpecialOrders();
      setOrders(res.data.items || []);
    } catch (e) {
      console.error('Failed to load special orders:', e);
    }
    setLoading(false);
  }

  const statusColors = {
    pending: 'bg-yellow-100 text-yellow-800',
    quoted: 'bg-blue-100 text-blue-800',
    ordered: 'bg-purple-100 text-purple-800',
    received: 'bg-green-100 text-green-800',
    cancelled: 'bg-gray-100 text-gray-800',
  };

  if (loading) {
    return <div className="p-4 text-center text-gray-500">Loading...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Special Orders</h1>
      <p className="text-sm text-gray-600">Track your special order requests for custom springs.</p>

      {orders.length === 0 ? (
        <div className="bg-white rounded-lg border p-8 text-center text-gray-500">
          No special orders yet. Use the Spring Builder to submit one.
        </div>
      ) : (
        <div className="bg-white rounded-lg border overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Spring Spec</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Qty</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Quote</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Submitted</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {orders.map(order => (
                <tr key={order.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium">#{order.id}</td>
                  <td className="px-4 py-3 text-sm font-mono">
                    .{(order.wire_diameter * 1000).toFixed(0)}" x {order.coil_diameter}" {order.wind_direction}
                    <span className="text-gray-400 ml-1">({order.spring_length}")</span>
                  </td>
                  <td className="px-4 py-3 text-sm">{order.quantity}</td>
                  <td className="px-4 py-3 text-sm">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${statusColors[order.status] || 'bg-gray-100'}`}>
                      {order.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {order.quoted_price ? (
                      <span className="font-medium">${order.quoted_price.toFixed(2)}</span>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                    {order.quoted_lead_time_days && (
                      <span className="text-gray-400 ml-1">({order.quoted_lead_time_days}d)</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {order.created_at ? new Date(order.created_at).toLocaleDateString() : '-'}
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
