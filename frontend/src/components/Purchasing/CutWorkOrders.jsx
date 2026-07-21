import { useState, useEffect } from 'react';
import { purchasingApi } from '../../api/client';

// The yay/nay approval window for cut work orders. Each card is one sales order
// that becomes shippable NOW by cutting stock on hand — showing the donor
// inventory that triggered it, the exact item-journal move, and prior verdicts.
export default function CutWorkOrders() {
  const [wos, setWos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);        // so_number currently deciding
  const [message, setMessage] = useState(null);
  const [rejecting, setRejecting] = useState(null); // so_number showing reason box
  const [reason, setReason] = useState('');

  useEffect(() => { load(); }, []);

  async function load() {
    setLoading(true);
    try {
      const res = await purchasingApi.listCutWorkOrders();
      setWos(res.data.work_orders || []);
    } catch (e) {
      setMessage({ type: 'error', text: `Failed to load: ${e.response?.data?.detail || e.message}` });
    }
    setLoading(false);
  }

  async function decide(wo, approve) {
    setBusy(wo.so_number);
    setMessage(null);
    try {
      if (approve) {
        await purchasingApi.approveCutWorkOrder({ so_number: wo.so_number });
        setMessage({ type: 'success', text: `${wo.so_number} approved — journal ${wo.journal.document_no} ready to post.` });
      } else {
        await purchasingApi.rejectCutWorkOrder({ so_number: wo.so_number, reason });
        setMessage({ type: 'success', text: `${wo.so_number} rejected.` });
      }
      setRejecting(null);
      setReason('');
      setWos((list) => list.filter((w) => w.so_number !== wo.so_number));
    } catch (e) {
      setMessage({ type: 'error', text: `Failed: ${e.response?.data?.detail || e.message}` });
    }
    setBusy(null);
  }

  const money = (n) => `$${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  if (loading) return <div className="p-6 text-gray-500">Loading cut proposals…</div>;

  const totalAvoided = wos.reduce((s, w) => s + (w.purchase_avoided || 0), 0);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-bold">Cut Work Orders</h1>
        <button onClick={load} className="text-sm text-blue-600 hover:underline">Refresh</button>
      </div>
      <p className="text-gray-500 mb-4">
        Jobs that can ship <span className="font-semibold">now</span> by cutting stock on hand — no purchase needed.
        Approve to generate the inventory move; reject to teach the engine why not.
      </p>

      {message && (
        <div className={`mb-4 rounded p-3 text-sm ${message.type === 'error' ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
          {message.text}
        </div>
      )}

      {wos.length === 0 ? (
        <div className="rounded border border-dashed p-8 text-center text-gray-400">
          No cut proposals right now — nothing shippable from cuttable stock.
        </div>
      ) : (
        <>
          <div className="mb-4 text-sm text-gray-600">
            {wos.length} job{wos.length === 1 ? '' : 's'} shippable now · {money(totalAvoided)} purchase avoided
          </div>
          <div className="space-y-4">
            {wos.map((wo) => (
              <WorkOrderCard
                key={wo.so_number}
                wo={wo}
                busy={busy === wo.so_number}
                rejecting={rejecting === wo.so_number}
                reason={reason}
                setReason={setReason}
                onApprove={() => decide(wo, true)}
                onStartReject={() => { setRejecting(wo.so_number); setReason(''); }}
                onCancelReject={() => setRejecting(null)}
                onConfirmReject={() => decide(wo, false)}
                money={money}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function WorkOrderCard({ wo, busy, rejecting, reason, setReason, onApprove, onStartReject, onCancelReject, onConfirmReject, money }) {
  const anyOverTol = wo.all_within_tolerance === false;

  return (
    <div className="rounded-lg border shadow-sm bg-white">
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-lg">{wo.so_number}</span>
          {wo.makes_invoiceable && (
            <span className="rounded-full bg-green-100 text-green-700 text-xs px-2 py-0.5">Invoiceable now</span>
          )}
          {anyOverTol && (
            <span className="rounded-full bg-amber-100 text-amber-700 text-xs px-2 py-0.5">Over waste limit</span>
          )}
        </div>
        <span className="text-sm text-gray-500">{money(wo.purchase_avoided)} avoided</span>
      </div>

      {/* Cuts — each shows the donor inventory that triggers the option */}
      <div className="px-4 py-3 space-y-2">
        {wo.cuts.map((c, i) => (
          <div key={i} className="text-sm">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium">{c.qty_needed}× {c.target_sku}</span>
              <span className="text-gray-400">←</span>
              <span>cut from <span className="font-medium">{c.donor_sku}</span> ({c.donor_length})</span>
              <span className={`text-xs rounded px-1.5 py-0.5 ${c.donor_on_hand > 0 ? 'bg-blue-50 text-blue-700' : 'bg-gray-100 text-gray-500'}`}>
                {c.donor_on_hand} in stock
              </span>
              {c.prior_verdict && (
                <span className={`text-xs rounded px-1.5 py-0.5 ${c.prior_verdict.verdict === 'approved' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                  previously {c.prior_verdict.verdict}
                </span>
              )}
            </div>
            <div className="text-xs text-gray-500 ml-1">
              {c.pieces_yielded} piece{c.pieces_yielded === 1 ? '' : 's'} · scrap {c.scrap}
              {c.recovered !== "0'0\"" && <> · recovers {c.recovered} reusable stock</>}
              {c.note && <> · <span className="text-amber-600">{c.note}</span></>}
            </div>
          </div>
        ))}
      </div>

      {/* The inventory move that will be posted */}
      <div className="px-4 py-2 bg-gray-50 border-t text-xs font-mono text-gray-600">
        <div className="text-gray-400 mb-1">Item journal · {wo.journal.document_no}</div>
        {wo.journal.lines.map((l, i) => (
          <div key={i}>
            <span className={l.entry_type.startsWith('Negative') ? 'text-red-600' : 'text-green-600'}>
              {l.entry_type.startsWith('Negative') ? '−' : '+'}{l.quantity}
            </span>{' '}
            {l.item_no} <span className="text-gray-400">{l.entry_type}</span>
          </div>
        ))}
      </div>

      {/* Decision */}
      <div className="px-4 py-3 border-t">
        {rejecting ? (
          <div className="flex items-center gap-2">
            <input
              autoFocus
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why not? (e.g. saving that stock for a bigger job)"
              className="flex-1 border rounded px-2 py-1 text-sm"
            />
            <button disabled={busy} onClick={onConfirmReject}
              className="px-3 py-1 rounded bg-red-600 text-white text-sm disabled:opacity-50">
              Confirm reject
            </button>
            <button onClick={onCancelReject} className="px-3 py-1 rounded border text-sm">Cancel</button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button disabled={busy} onClick={onApprove}
              className="px-4 py-1.5 rounded bg-green-600 text-white text-sm font-medium disabled:opacity-50">
              {busy ? 'Working…' : 'Approve'}
            </button>
            <button disabled={busy} onClick={onStartReject}
              className="px-4 py-1.5 rounded border text-sm disabled:opacity-50">
              Reject
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
