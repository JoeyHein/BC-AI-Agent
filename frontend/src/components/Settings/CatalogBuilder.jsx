import { useState, useEffect } from 'react';
import { catalogApi } from '../../api/client';

export default function CatalogBuilder() {
  const [stats, setStats] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => { loadStats(); }, []);
  useEffect(() => { loadTabData(); }, [activeTab]);

  async function loadStats() {
    try {
      const res = await catalogApi.getStats();
      setStats(res.data);
    } catch (e) {
      console.error('Failed to load stats:', e);
    }
  }

  async function loadTabData() {
    setLoading(true);
    try {
      let res;
      switch (activeTab) {
        case 'staging':
          res = await catalogApi.getStaging({ limit: 100 });
          setItems(res.data.items || []);
          break;
        case 'review':
          res = await catalogApi.getReviewQueue({ resolved: false, limit: 100 });
          setItems(res.data.items || []);
          break;
        case 'duplicates':
          res = await catalogApi.getDuplicates({ resolved: false, limit: 100 });
          setItems(res.data.items || []);
          break;
        case 'parts':
          res = await catalogApi.getParts({ limit: 100 });
          setItems(res.data.items || []);
          break;
        case 'special-orders':
          res = await catalogApi.getSpecialOrders({ limit: 100 });
          setItems(res.data.items || []);
          break;
        default:
          setItems([]);
      }
    } catch (e) {
      console.error('Failed to load tab data:', e);
    }
    setLoading(false);
  }

  async function runPipeline() {
    setRunning(true);
    setMessage(null);
    try {
      const res = await catalogApi.runPipeline();
      setMessage({ type: 'success', text: `Pipeline complete! Extracted: ${res.data.stats.extracted}, Published: ${res.data.stats.published}, Review Queue: ${res.data.stats.review_queue}` });
      loadStats();
      loadTabData();
    } catch (e) {
      setMessage({ type: 'error', text: `Pipeline failed: ${e.response?.data?.detail || e.message}` });
    }
    setRunning(false);
  }

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'staging', label: 'Staging' },
    { id: 'review', label: 'Review Queue' },
    { id: 'duplicates', label: 'Duplicates' },
    { id: 'parts', label: 'Parts Catalog' },
    { id: 'special-orders', label: 'Special Orders' },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900">Catalog Builder</h2>
        <button
          onClick={runPipeline}
          disabled={running}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {running ? 'Running Pipeline...' : 'Run Pipeline'}
        </button>
      </div>

      {message && (
        <div className={`p-3 rounded-lg ${message.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
          {message.text}
        </div>
      )}

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Total Staged" value={stats.staging?.total || 0} />
          <StatCard label="Parts Catalog" value={stats.parts?.total || 0} />
          <StatCard label="Active Parts" value={stats.parts?.active || 0} />
          <StatCard label="Pending Review" value={stats.review_queue?.pending || 0} />
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex space-x-4">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`py-2 px-3 text-sm font-medium border-b-2 ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="min-h-[300px]">
        {loading ? (
          <div className="text-center py-8 text-gray-500">Loading...</div>
        ) : activeTab === 'overview' ? (
          <OverviewTab stats={stats} />
        ) : activeTab === 'staging' ? (
          <StagingTable items={items} />
        ) : activeTab === 'review' ? (
          <ReviewTable items={items} onResolve={loadTabData} />
        ) : activeTab === 'duplicates' ? (
          <DuplicatesTable items={items} />
        ) : activeTab === 'parts' ? (
          <PartsTable items={items} onUpdate={() => { loadTabData(); loadStats(); }} setMessage={setMessage} />
        ) : activeTab === 'special-orders' ? (
          <SpecialOrdersTable items={items} onUpdate={loadTabData} />
        ) : null}
      </div>
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="bg-white rounded-lg border p-4">
      <div className="text-sm text-gray-500">{label}</div>
      <div className="text-2xl font-bold text-gray-900">{value}</div>
    </div>
  );
}

function OverviewTab({ stats }) {
  if (!stats) return <div className="text-gray-500">No data yet. Run the pipeline to get started.</div>;
  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-medium mb-2">Staging</h3>
        <p className="text-sm text-gray-600">Total: {stats.staging?.total}, Processed: {stats.staging?.processed}, Unprocessed: {stats.staging?.unprocessed}</p>
      </div>
      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-medium mb-2">Parts Catalog</h3>
        <p className="text-sm text-gray-600">Total: {stats.parts?.total}, Active: {stats.parts?.active}, Pending Review: {stats.parts?.pending_review}</p>
      </div>
      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-medium mb-2">Queues</h3>
        <p className="text-sm text-gray-600">Review Queue: {stats.review_queue?.pending} pending, Duplicates: {stats.duplicates?.pending} pending</p>
      </div>
    </div>
  );
}

function StagingTable({ items }) {
  if (!items.length) return <div className="text-gray-500 py-4">No staged items.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Item #</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Description</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Category</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Processed</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {items.map(item => (
            <tr key={item.id}>
              <td className="px-4 py-2 text-sm font-mono">{item.bc_item_number}</td>
              <td className="px-4 py-2 text-sm">{item.bc_description}</td>
              <td className="px-4 py-2 text-sm">{item.classified_category || '-'}</td>
              <td className="px-4 py-2 text-sm">{item.is_processed ? 'Yes' : 'No'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReviewTable({ items, onResolve }) {
  const [resolving, setResolving] = useState(null);
  const [category, setCategory] = useState('');

  async function handleResolve(reviewId) {
    if (!category) return;
    setResolving(reviewId);
    try {
      await catalogApi.resolveReview(reviewId, { category });
      setCategory('');
      onResolve();
    } catch (e) {
      console.error('Failed to resolve:', e);
    }
    setResolving(null);
  }

  if (!items.length) return <div className="text-gray-500 py-4">No items pending review.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Item #</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Description</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Reason</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {items.map(item => (
            <tr key={item.id}>
              <td className="px-4 py-2 text-sm font-mono">{item.bc_item_number}</td>
              <td className="px-4 py-2 text-sm">{item.bc_description}</td>
              <td className="px-4 py-2 text-sm">{item.reason}</td>
              <td className="px-4 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <select
                    value={category}
                    onChange={e => setCategory(e.target.value)}
                    className="text-sm border rounded px-2 py-1"
                  >
                    <option value="">Select category</option>
                    <option value="spring">Spring</option>
                    <option value="panel">Panel</option>
                    <option value="track">Track</option>
                    <option value="hardware">Hardware</option>
                    <option value="shaft">Shaft</option>
                    <option value="plastic">Plastic</option>
                    <option value="glazing_kit">Glazing Kit</option>
                    <option value="other">Other</option>
                  </select>
                  <button
                    onClick={() => handleResolve(item.id)}
                    disabled={resolving === item.id || !category}
                    className="px-2 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700 disabled:opacity-50"
                  >
                    {resolving === item.id ? '...' : 'Resolve'}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DuplicatesTable({ items }) {
  if (!items.length) return <div className="text-gray-500 py-4">No duplicate candidates.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Item A</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Item B</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Score</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Reasons</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {items.map(item => (
            <tr key={item.id}>
              <td className="px-4 py-2 text-sm font-mono">{item.item_a_number}</td>
              <td className="px-4 py-2 text-sm font-mono">{item.item_b_number}</td>
              <td className="px-4 py-2 text-sm">{(item.similarity_score * 100).toFixed(0)}%</td>
              <td className="px-4 py-2 text-sm">{item.match_reasons?.join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PartsTable({ items, onUpdate, setMessage }) {
  const [activating, setActivating] = useState(false);
  const pendingCount = items.filter(i => i.catalog_status === 'pending_review').length;

  async function handleActivateAll() {
    setActivating(true);
    try {
      const res = await catalogApi.bulkActivateParts({ activate_all_pending: true });
      setMessage({ type: 'success', text: `Activated ${res.data.activated_count} part(s).` });
      onUpdate();
    } catch (e) {
      setMessage({ type: 'error', text: `Activation failed: ${e.response?.data?.detail || e.message}` });
    }
    setActivating(false);
  }

  async function handleToggleStatus(partId, currentStatus) {
    const newStatus = currentStatus === 'active' ? 'pending_review' : 'active';
    try {
      await catalogApi.updatePartStatus(partId, newStatus);
      onUpdate();
    } catch (e) {
      setMessage({ type: 'error', text: `Status update failed: ${e.response?.data?.detail || e.message}` });
    }
  }

  if (!items.length) return <div className="text-gray-500 py-4">No parts in catalog yet.</div>;
  return (
    <div className="space-y-3">
      {pendingCount > 0 && (
        <div className="flex items-center justify-between bg-yellow-50 border border-yellow-200 rounded-lg p-3">
          <span className="text-sm text-yellow-800">{pendingCount} part(s) pending review</span>
          <button
            onClick={handleActivateAll}
            disabled={activating}
            className="px-3 py-1 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
          >
            {activating ? 'Activating...' : 'Activate All Pending'}
          </button>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Item #</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Description</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Category</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Status</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Unit Cost</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {items.map(item => (
              <tr key={item.id}>
                <td className="px-4 py-2 text-sm font-mono">{item.bc_item_number}</td>
                <td className="px-4 py-2 text-sm">{item.bc_description}</td>
                <td className="px-4 py-2 text-sm capitalize">{item.category}</td>
                <td className="px-4 py-2 text-sm">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${
                    item.catalog_status === 'active' ? 'bg-green-100 text-green-800' :
                    item.catalog_status === 'pending_review' ? 'bg-yellow-100 text-yellow-800' :
                    'bg-gray-100 text-gray-800'
                  }`}>
                    {item.catalog_status}
                  </span>
                </td>
                <td className="px-4 py-2 text-sm">{item.unit_cost != null ? `$${item.unit_cost.toFixed(2)}` : '-'}</td>
                <td className="px-4 py-2 text-sm">
                  <button
                    onClick={() => handleToggleStatus(item.id, item.catalog_status)}
                    className={`px-2 py-1 text-xs rounded ${
                      item.catalog_status === 'active'
                        ? 'bg-yellow-100 text-yellow-800 hover:bg-yellow-200'
                        : 'bg-green-100 text-green-800 hover:bg-green-200'
                    }`}
                  >
                    {item.catalog_status === 'active' ? 'Deactivate' : 'Activate'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SpecialOrdersTable({ items, onUpdate }) {
  const [updating, setUpdating] = useState(null);

  async function handleStatusUpdate(orderId, newStatus) {
    setUpdating(orderId);
    try {
      await catalogApi.updateSpecialOrder(orderId, { status: newStatus });
      onUpdate();
    } catch (e) {
      console.error('Failed to update:', e);
    }
    setUpdating(null);
  }

  if (!items.length) return <div className="text-gray-500 py-4">No special orders.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">ID</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Wire</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Coil</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Wind</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Qty</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Status</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {items.map(item => (
            <tr key={item.id}>
              <td className="px-4 py-2 text-sm">{item.id}</td>
              <td className="px-4 py-2 text-sm">.{(item.wire_diameter * 1000).toFixed(0)}</td>
              <td className="px-4 py-2 text-sm">{item.coil_diameter}"</td>
              <td className="px-4 py-2 text-sm">{item.wind_direction}</td>
              <td className="px-4 py-2 text-sm">{item.quantity}</td>
              <td className="px-4 py-2 text-sm">
                <span className={`px-2 py-0.5 rounded-full text-xs ${
                  item.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                  item.status === 'quoted' ? 'bg-blue-100 text-blue-800' :
                  item.status === 'ordered' ? 'bg-purple-100 text-purple-800' :
                  item.status === 'received' ? 'bg-green-100 text-green-800' :
                  'bg-gray-100 text-gray-800'
                }`}>
                  {item.status}
                </span>
              </td>
              <td className="px-4 py-2 text-sm">
                {item.status === 'pending' && (
                  <button
                    onClick={() => handleStatusUpdate(item.id, 'quoted')}
                    disabled={updating === item.id}
                    className="px-2 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50"
                  >
                    Quote
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
