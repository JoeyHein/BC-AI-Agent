import { useState, useEffect } from 'react';
import { poAgentApi } from '../../api/client';

export default function POAgentDashboard() {
  const [stats, setStats] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState(null);
  const [filter, setFilter] = useState('draft');
  const [expandedDraft, setExpandedDraft] = useState(null);

  useEffect(() => { loadData(); }, [filter]);

  async function loadData() {
    setLoading(true);
    try {
      const [statsRes, draftsRes] = await Promise.all([
        poAgentApi.getStats(),
        poAgentApi.getDrafts({ status_filter: filter !== 'all' ? filter : undefined, limit: 100 }),
      ]);
      setStats(statsRes.data);
      setDrafts(draftsRes.data.items || []);
    } catch (e) {
      console.error('Failed to load PO data:', e);
    }
    setLoading(false);
  }

  async function runGeneration() {
    setRunning(true);
    setMessage(null);
    try {
      const res = await poAgentApi.runGeneration();
      const s = res.data.stats;
      setMessage({
        type: 'success',
        text: `Generated ${s.drafts_created} PO draft(s) from ${s.signals_processed} signals across ${s.vendors} vendor(s).`,
      });
      loadData();
    } catch (e) {
      setMessage({ type: 'error', text: `Generation failed: ${e.response?.data?.detail || e.message}` });
    }
    setRunning(false);
  }

  async function handleApprove(draftId) {
    try {
      const res = await poAgentApi.approveDraft(draftId);
      setMessage({
        type: 'success',
        text: res.data.bc_po_number
          ? `PO approved and submitted to BC as ${res.data.bc_po_number}`
          : `PO ${draftId} approved.`,
      });
      loadData();
    } catch (e) {
      setMessage({ type: 'error', text: `Approval failed: ${e.response?.data?.detail || e.message}` });
    }
  }

  async function handleReject(draftId) {
    const reason = prompt('Rejection reason (optional):');
    try {
      await poAgentApi.rejectDraft(draftId, { reason });
      loadData();
    } catch (e) {
      setMessage({ type: 'error', text: `Rejection failed: ${e.response?.data?.detail || e.message}` });
    }
  }

  const statusColors = {
    draft: 'bg-yellow-100 text-yellow-800',
    approved: 'bg-blue-100 text-blue-800',
    submitted: 'bg-green-100 text-green-800',
    rejected: 'bg-red-100 text-red-800',
    failed: 'bg-red-100 text-red-800',
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900">PO Generation Agent</h2>
        <button
          onClick={runGeneration}
          disabled={running}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {running ? 'Generating...' : 'Generate POs'}
        </button>
      </div>

      {message && (
        <div className={`p-3 rounded-lg ${message.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
          {message.text}
        </div>
      )}

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-white rounded-lg border p-4">
            <div className="text-sm text-gray-500">Mode</div>
            <div className="text-lg font-bold capitalize">{stats.mode?.replace('_', ' ')}</div>
          </div>
          <div className="bg-white rounded-lg border p-4">
            <div className="text-sm text-gray-500">Total POs</div>
            <div className="text-2xl font-bold">{stats.total_pos}</div>
          </div>
          <div className="bg-white rounded-lg border p-4">
            <div className="text-sm text-gray-500">Pending Drafts</div>
            <div className="text-2xl font-bold text-yellow-600">{stats.drafts}</div>
          </div>
          <div className="bg-white rounded-lg border p-4">
            <div className="text-sm text-gray-500">Approved</div>
            <div className="text-2xl font-bold text-green-600">{stats.approved}</div>
          </div>
          <div className="bg-white rounded-lg border p-4">
            <div className="text-sm text-gray-500">Approval Rate</div>
            <div className="text-2xl font-bold">{stats.approval_rate}%</div>
          </div>
        </div>
      )}

      {/* Draft-only period warning */}
      {stats?.draft_only_until && (
        <div className="bg-blue-50 border border-blue-200 p-3 rounded-lg text-sm text-blue-800">
          Draft-only period active until {new Date(stats.draft_only_until).toLocaleDateString()}. All POs require manual approval.
        </div>
      )}

      {/* Filter Tabs */}
      <div className="flex space-x-2">
        {['draft', 'approved', 'submitted', 'rejected', 'all'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1 text-sm rounded-full capitalize ${
              filter === f ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Drafts Table */}
      {loading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : drafts.length === 0 ? (
        <div className="text-center py-8 text-gray-500">No PO drafts found.</div>
      ) : (
        <div className="space-y-3">
          {drafts.map(draft => (
            <div key={draft.id} className="bg-white rounded-lg border overflow-hidden">
              <div
                className="p-4 flex items-center justify-between cursor-pointer hover:bg-gray-50"
                onClick={() => setExpandedDraft(expandedDraft === draft.id ? null : draft.id)}
              >
                <div className="flex items-center gap-4">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${statusColors[draft.status]}`}>
                    {draft.status}
                  </span>
                  <span className="font-medium">{draft.vendor_name}</span>
                  <span className="text-sm text-gray-500">{draft.line_count} item(s)</span>
                  {draft.bc_po_number && (
                    <span className="text-sm font-mono text-green-600">BC#{draft.bc_po_number}</span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-medium">
                    ${draft.total_amount?.toFixed(2) || '0.00'} {draft.currency}
                  </span>
                  {draft.status === 'draft' && (
                    <div className="flex gap-2" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => handleApprove(draft.id)}
                        className="px-3 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleReject(draft.id)}
                        className="px-3 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-700"
                      >
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* Expanded line items */}
              {expandedDraft === draft.id && draft.line_items && (
                <div className="border-t bg-gray-50 p-4">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="text-gray-500 text-xs">
                        <th className="text-left py-1">Item</th>
                        <th className="text-left py-1">Description</th>
                        <th className="text-right py-1">Qty</th>
                        <th className="text-right py-1">Unit Cost</th>
                        <th className="text-right py-1">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {draft.line_items.map((line, i) => (
                        <tr key={i} className="border-t border-gray-200">
                          <td className="py-1 font-mono">{line.bc_item_number}</td>
                          <td className="py-1 text-gray-600">{line.description}</td>
                          <td className="py-1 text-right">{line.quantity}</td>
                          <td className="py-1 text-right">${line.unit_cost?.toFixed(2)}</td>
                          <td className="py-1 text-right font-medium">${line.line_total?.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {draft.rejection_reason && (
                    <div className="mt-2 text-sm text-red-600">
                      Rejection reason: {draft.rejection_reason}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
