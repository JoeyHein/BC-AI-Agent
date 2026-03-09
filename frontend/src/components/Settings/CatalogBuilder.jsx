import { useState, useEffect } from 'react';
import { catalogApi } from '../../api/client';

export default function CatalogBuilder() {
  const [stats, setStats] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState(null);
  const [catalogVisible, setCatalogVisible] = useState(false);
  const [togglingVisibility, setTogglingVisibility] = useState(false);

  useEffect(() => { loadStats(); }, []);
  useEffect(() => { loadTabData(); }, [activeTab]);

  async function loadStats() {
    try {
      const res = await catalogApi.getStats();
      setStats(res.data);
      if (res.data.catalog_visible !== undefined) {
        setCatalogVisible(res.data.catalog_visible);
      }
    } catch (e) {
      console.error('Failed to load stats:', e);
    }
  }

  async function toggleVisibility() {
    setTogglingVisibility(true);
    try {
      const newVal = !catalogVisible;
      await catalogApi.setVisibility(newVal);
      setCatalogVisible(newVal);
      setMessage({ type: 'success', text: `Catalog is now ${newVal ? 'visible' : 'hidden'} to customers.` });
    } catch (e) {
      setMessage({ type: 'error', text: `Failed to update visibility: ${e.response?.data?.detail || e.message}` });
    }
    setTogglingVisibility(false);
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
          // PartsTable manages its own data loading
          setItems([]);
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
        <div className="flex items-center gap-3">
          <button
            onClick={runPipeline}
            disabled={running}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {running ? 'Running Pipeline...' : 'Run Pipeline'}
          </button>
        </div>
      </div>

      {/* Customer Visibility Toggle */}
      <div className={`flex items-center justify-between p-4 rounded-lg border ${catalogVisible ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200'}`}>
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Customer Catalog Visibility</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {catalogVisible
              ? 'Customers can browse the parts catalog on the portal.'
              : 'Parts catalog is hidden from customers.'}
          </p>
        </div>
        <button
          onClick={toggleVisibility}
          disabled={togglingVisibility}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            catalogVisible ? 'bg-green-600' : 'bg-gray-300'
          } ${togglingVisibility ? 'opacity-50' : ''}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            catalogVisible ? 'translate-x-6' : 'translate-x-1'
          }`} />
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
          <PartsTable onStatsChange={loadStats} setMessage={setMessage} />
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

const PART_CATEGORIES = [
  { value: '', label: 'All Categories' },
  { value: 'spring', label: 'Springs' },
  { value: 'panel', label: 'Panels' },
  { value: 'track', label: 'Tracks' },
  { value: 'shaft', label: 'Shafts' },
  { value: 'hardware_kit', label: 'Hardware Kits' },
  { value: 'hardware', label: 'Hardware' },
  { value: 'plastic', label: 'Plastics/Weather Strip' },
  { value: 'aluminum', label: 'Aluminum' },
  { value: 'glazing_kit', label: 'Glazing Kits' },
];

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'active', label: 'Active' },
  { value: 'pending_review', label: 'Pending Review' },
];

function PartsTable({ onStatsChange, setMessage }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [activating, setActivating] = useState(false);
  const [category, setCategory] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const pageSize = 50;

  useEffect(() => { loadParts(); }, [category, statusFilter, page]);

  async function loadParts() {
    setLoading(true);
    try {
      const params = { limit: pageSize, skip: page * pageSize };
      if (category) params.category = category;
      if (statusFilter) params.status = statusFilter;
      if (search) params.search = search;
      const res = await catalogApi.getParts(params);
      setItems(res.data.items || []);
    } catch (e) {
      console.error('Failed to load parts:', e);
    }
    setLoading(false);
  }

  function handleSearch(e) {
    e.preventDefault();
    setPage(0);
    loadParts();
  }

  async function handleActivateCategory() {
    const target = category || 'all pending';
    if (!confirm(`Activate all pending parts${category ? ` in "${category}"` : ''}?`)) return;
    setActivating(true);
    try {
      const body = category
        ? { category }
        : { activate_all_pending: true };
      const res = await catalogApi.bulkActivateParts(body);
      setMessage({ type: 'success', text: `Activated ${res.data.activated_count} part(s).` });
      loadParts();
      onStatsChange();
    } catch (e) {
      setMessage({ type: 'error', text: `Activation failed: ${e.response?.data?.detail || e.message}` });
    }
    setActivating(false);
  }

  async function handleToggleStatus(partId, currentStatus) {
    const newStatus = currentStatus === 'active' ? 'pending_review' : 'active';
    try {
      await catalogApi.updatePartStatus(partId, newStatus);
      loadParts();
      onStatsChange();
    } catch (e) {
      setMessage({ type: 'error', text: `Status update failed: ${e.response?.data?.detail || e.message}` });
    }
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Category</label>
          <select
            value={category}
            onChange={e => { setCategory(e.target.value); setPage(0); }}
            className="px-3 py-2 border rounded-lg text-sm"
          >
            {PART_CATEGORIES.map(c => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Status</label>
          <select
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(0); }}
            className="px-3 py-2 border rounded-lg text-sm"
          >
            {STATUS_OPTIONS.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>
        <form onSubmit={handleSearch} className="flex gap-2">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Search</label>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Item # or description"
              className="px-3 py-2 border rounded-lg text-sm w-48"
            />
          </div>
          <button type="submit" className="self-end px-3 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm hover:bg-gray-200">
            Search
          </button>
        </form>
        <button
          onClick={handleActivateCategory}
          disabled={activating}
          className="self-end px-3 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 disabled:opacity-50"
        >
          {activating ? 'Activating...' : category ? `Activate All "${category}"` : 'Activate All Pending'}
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : items.length === 0 ? (
        <div className="text-gray-500 py-4">No parts found.</div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Item #</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Description</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Category</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Subcategory</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Status</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Cost</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {items.map(item => (
                  <tr key={item.id}>
                    <td className="px-4 py-2 text-sm font-mono">{item.bc_item_number}</td>
                    <td className="px-4 py-2 text-sm max-w-xs truncate">{item.bc_description}</td>
                    <td className="px-4 py-2 text-sm capitalize">{item.category}</td>
                    <td className="px-4 py-2 text-sm capitalize">{item.subcategory || '-'}</td>
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
          {/* Pagination */}
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-500">
              Showing {page * pageSize + 1}-{page * pageSize + items.length}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                className="px-3 py-1 border rounded text-sm disabled:opacity-50 hover:bg-gray-50"
              >
                Previous
              </button>
              <button
                onClick={() => setPage(p => p + 1)}
                disabled={items.length < pageSize}
                className="px-3 py-1 border rounded text-sm disabled:opacity-50 hover:bg-gray-50"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
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
