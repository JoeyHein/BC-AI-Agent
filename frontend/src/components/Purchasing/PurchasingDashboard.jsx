import { useState, useEffect } from 'react';
import { purchasingApi } from '../../api/client';

const UNASSIGNED = 'Unassigned';

export default function PurchasingDashboard() {
  const [data, setData] = useState(null);
  const [brief, setBrief] = useState(null);      // morning brief (same one the digest sends)
  const [vendors, setVendors] = useState([]);
  const [sel, setSel] = useState({});            // item_no -> { selected, qty }
  const [expanded, setExpanded] = useState({});  // vendor_name -> bool
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);        // action label currently running
  const [message, setMessage] = useState(null);
  const [horizon, setHorizon] = useState(5);     // delivery horizon in weeks (0 = all)

  useEffect(() => { load(); }, [horizon]);

  async function load() {
    setLoading(true);
    try {
      const [reqRes, venRes] = await Promise.all([
        purchasingApi.getRequirements({ horizon_weeks: horizon }),
        purchasingApi.listVendors(),
      ]);
      setData(reqRes.data);
      setVendors(venRes.data.vendors || []);
      const initSel = {};
      (reqRes.data.items || []).forEach((r) => {
        if (r.net_need > 0) initSel[r.item_no] = { selected: true, qty: r.net_need };
      });
      setSel(initSel);
      // Expand the first real vendor group by default.
      const firstReal = (reqRes.data.vendors || []).find((g) => g.vendor_name !== UNASSIGNED);
      setExpanded(firstReal ? { [firstReal.vendor_name]: true } : {});
      // Brief is a nice-to-have on this page — never let it block the buy list.
      purchasingApi.getBrief().then((r) => setBrief(r.data)).catch(() => setBrief(null));
    } catch (e) {
      setMessage({ type: 'error', text: `Failed to load: ${e.response?.data?.detail || e.message}` });
    }
    setLoading(false);
  }

  function toggle(item) {
    setSel((s) => ({ ...s, [item]: { ...s[item], selected: !s[item]?.selected } }));
  }
  function setQty(item, qty) {
    setSel((s) => ({ ...s, [item]: { ...s[item], qty: parseFloat(qty) || 0 } }));
  }

  async function refreshVendors() {
    setBusy('refresh');
    setMessage(null);
    try {
      const res = await purchasingApi.refreshVendors();
      setMessage({ type: 'success', text: `Vendor map refreshed (${res.data.stats.history_upserts} from history, ${res.data.stats.bc_upserts} from BC).` });
      await load();
    } catch (e) {
      setMessage({ type: 'error', text: `Refresh failed: ${e.response?.data?.detail || e.message}` });
    }
    setBusy(null);
  }

  async function refreshBrief() {
    setBusy('brief');
    setMessage(null);
    try {
      const res = await purchasingApi.runBrief();
      setBrief(res.data);
    } catch (e) {
      setMessage({ type: 'error', text: `Brief failed: ${e.response?.data?.detail || e.message}` });
    }
    setBusy(null);
  }

  async function sendReport() {
    setBusy('report');
    setMessage(null);
    try {
      const res = await purchasingApi.sendReport({});
      setMessage(res.data.sent
        ? { type: 'success', text: `Digest emailed to ${(res.data.recipients || []).join(', ')}.` }
        : { type: 'error', text: `Digest not sent: ${res.data.error || res.data.reason || 'unknown'}` });
    } catch (e) {
      setMessage({ type: 'error', text: `Send failed: ${e.response?.data?.detail || e.message}` });
    }
    setBusy(null);
  }

  async function assign(item, vendorNo) {
    const v = vendors.find((x) => x.number === vendorNo);
    setBusy(`assign-${item}`);
    try {
      await purchasingApi.assignVendor({ item_no: item, vendor_no: vendorNo, vendor_name: v?.name || vendorNo });
      await load();
    } catch (e) {
      setMessage({ type: 'error', text: `Assign failed: ${e.response?.data?.detail || e.message}` });
    }
    setBusy(null);
  }

  async function generatePO(group) {
    const lines = group.items
      .filter((r) => sel[r.item_no]?.selected && (sel[r.item_no]?.qty || 0) > 0)
      .map((r) => ({
        item_no: r.item_no,
        description: r.description,
        quantity: sel[r.item_no].qty,
        unit_cost: r.unit_cost,
      }));
    if (lines.length === 0) {
      setMessage({ type: 'error', text: 'Select at least one item with a quantity.' });
      return;
    }
    if (!window.confirm(`Create a PO in Business Central for ${group.vendor_name} with ${lines.length} line(s) and email it to the vendor?`)) return;

    setBusy(`po-${group.vendor_name}`);
    setMessage(null);
    try {
      const res = await purchasingApi.generatePO({
        vendor_no: group.vendor_no,
        vendor_name: group.vendor_name,
        lines,
      });
      const d = res.data;
      const emailMsg = d.emailed_to
        ? `emailed to ${d.emailed_to}`
        : `NOT emailed (${d.email_error || 'no vendor email'})`;
      setMessage({ type: d.emailed_to ? 'success' : 'warn', text: `PO ${d.bc_po_number} created in BC — ${emailMsg}.` });
      await load();
    } catch (e) {
      setMessage({ type: 'error', text: `PO failed: ${e.response?.data?.detail || e.message}` });
    }
    setBusy(null);
  }

  const fmt = (n) => `$${(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const msgClass = {
    success: 'bg-green-50 text-green-800',
    error: 'bg-red-50 text-red-800',
    warn: 'bg-yellow-50 text-yellow-800',
  };

  if (loading) return <div className="p-6 text-gray-500">Loading purchasing requirements…</div>;

  const s = data?.summary || {};
  return (
    <div className="space-y-6 p-2">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-2xl font-bold text-gray-900">Purchasing</h1>
        <div className="flex gap-2 items-center">
          <label className="text-sm text-gray-600">Delivery horizon:</label>
          <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}
            className="px-2 py-2 border rounded-lg text-sm">
            <option value={4}>4 weeks</option>
            <option value={5}>5 weeks</option>
            <option value={6}>6 weeks</option>
            <option value={8}>8 weeks</option>
            <option value={12}>12 weeks</option>
            <option value={0}>All (no horizon)</option>
          </select>
          <button onClick={load} className="px-3 py-2 bg-gray-100 rounded-lg hover:bg-gray-200 text-sm">Reload</button>
          <button onClick={refreshVendors} disabled={busy === 'refresh'}
            className="px-3 py-2 bg-gray-100 rounded-lg hover:bg-gray-200 text-sm disabled:opacity-50">
            {busy === 'refresh' ? 'Refreshing…' : 'Refresh vendor map'}
          </button>
          <button onClick={sendReport} disabled={busy === 'report'}
            className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm disabled:opacity-50">
            {busy === 'report' ? 'Sending…' : 'Email digest now'}
          </button>
        </div>
      </div>

      {message && <div className={`p-3 rounded-lg ${msgClass[message.type]}`}>{message.text}</div>}

      <MorningBrief data={brief} busy={busy === 'brief'} onRefresh={refreshBrief} />

      {!data?.production_included && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 p-3 rounded-lg text-sm">
          Production-order demand not included — BC production web services aren't published yet.
          Figures reflect open sales orders only.
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat label="Items to buy" value={s.shortfall_items} />
        <Stat label="Vendors" value={s.vendor_count} />
        <Stat label="Unassigned items" value={s.unassigned_items} warn={s.unassigned_items > 0} />
        <Stat label="Est. spend" value={fmt(s.estimated_cost)} />
      </div>

      {horizon > 0 && (
        <div className="text-sm text-gray-600">
          Showing material for orders due within <strong>{horizon} weeks</strong>
          {data?.horizon_cutoff ? ` (by ${data.horizon_cutoff})` : ''}.
          {s.deferred_orders > 0 && <> <strong>{s.deferred_orders}</strong> later order(s) deferred — not due yet.</>}
        </div>
      )}

      {(data?.vendors || []).map((group) => {
        const isUnassigned = group.vendor_name === UNASSIGNED;
        const open = !!expanded[group.vendor_name];
        return (
          <div key={group.vendor_name} className="bg-white rounded-lg border overflow-hidden">
            <div className="p-4 flex items-center justify-between cursor-pointer hover:bg-gray-50"
              onClick={() => setExpanded((e) => ({ ...e, [group.vendor_name]: !open }))}>
              <div className="flex items-center gap-3">
                <span className={`font-semibold ${isUnassigned ? 'text-red-700' : 'text-gray-900'}`}>{group.vendor_name}</span>
                {group.is_expedite && (
                  <span className="px-2 py-0.5 text-xs rounded-full bg-amber-100 text-amber-800 border border-amber-300"
                    title="Last-resort vendor — only for <1 week urgency. Confirm a preferred source (Upwardor / Lynx / Elton).">
                    expedite — confirm preferred
                  </span>
                )}
                <span className="text-sm text-gray-500">{group.item_count} item(s) · {fmt(group.estimated_cost)}</span>
              </div>
              <div className="flex items-center gap-3" onClick={(e) => e.stopPropagation()}>
                {!isUnassigned && (
                  <button onClick={() => generatePO(group)} disabled={busy === `po-${group.vendor_name}`}
                    className="px-3 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50">
                    {busy === `po-${group.vendor_name}` ? 'Creating PO…' : 'Generate PO'}
                  </button>
                )}
                <span className="text-gray-400 text-sm">{open ? '▾' : '▸'}</span>
              </div>
            </div>

            {open && (
              <div className="border-t overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50 text-gray-500 text-xs">
                    <tr>
                      {!isUnassigned && <th className="p-2 w-8"></th>}
                      <th className="p-2 text-left">Item</th>
                      <th className="p-2 text-left">Description</th>
                      <th className="p-2 text-right">Net need</th>
                      <th className="p-2 text-right">On hand</th>
                      <th className="p-2 text-right">On order</th>
                      <th className="p-2 text-right">Unit cost</th>
                      <th className="p-2 text-right">Last paid</th>
                      <th className="p-2 text-left">Last from</th>
                      <th className="p-2 text-right">Lead</th>
                      {!isUnassigned && <th className="p-2 text-right">Order qty</th>}
                      <th className="p-2 text-left">{isUnassigned ? 'Assign vendor' : 'Jobs'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.items.map((r) => (
                      <tr key={r.item_no} className="border-t border-gray-100">
                        {!isUnassigned && (
                          <td className="p-2 text-center">
                            <input type="checkbox" checked={!!sel[r.item_no]?.selected} onChange={() => toggle(r.item_no)} />
                          </td>
                        )}
                        <td className="p-2 font-mono">{r.item_no}</td>
                        <td className="p-2 text-gray-600">{r.description}</td>
                        <td className="p-2 text-right">{r.net_need} {r.unit_of_measure}</td>
                        <td className="p-2 text-right text-gray-500">{r.on_hand}</td>
                        <td className="p-2 text-right text-gray-500">{r.on_order}</td>
                        <td className="p-2 text-right">{fmt(r.unit_cost)}</td>
                        <td className="p-2 text-right">
                          {r.last_purchase_cost != null ? (
                            <span title={r.last_purchase_date || ''}>{fmt(r.last_purchase_cost)}</span>
                          ) : <span className="text-gray-300">—</span>}
                        </td>
                        <td className="p-2 text-left text-gray-500">
                          {r.last_purchase_vendor
                            ? <span className={r.last_purchase_vendor !== r.vendor_name ? 'text-amber-700' : ''}
                                    title={r.last_purchase_date || ''}>{r.last_purchase_vendor}</span>
                            : <span className="text-gray-300">—</span>}
                        </td>
                        <td className="p-2 text-right text-gray-500">
                          {r.lead_time_days != null ? `${r.lead_time_days}d` : <span className="text-gray-300">—</span>}
                        </td>
                        {!isUnassigned && (
                          <td className="p-2 text-right">
                            <input type="number" min="0" step="any" value={sel[r.item_no]?.qty ?? r.net_need}
                              onChange={(e) => setQty(r.item_no, e.target.value)}
                              className="w-20 border rounded px-1 py-0.5 text-right" />
                          </td>
                        )}
                        <td className="p-2 text-gray-500">
                          {isUnassigned ? (
                            <select defaultValue="" disabled={busy === `assign-${r.item_no}`}
                              onChange={(e) => e.target.value && assign(r.item_no, e.target.value)}
                              className="border rounded px-2 py-1 text-sm max-w-[200px]">
                              <option value="">Select vendor…</option>
                              {vendors.map((v) => <option key={v.number} value={v.number}>{v.name}</option>)}
                            </select>
                          ) : (
                            (r.jobs || []).join(', ')
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}

      {(data?.vendors || []).length === 0 && (
        <div className="text-center py-12 text-gray-500">No purchasing shortfalls right now. 🎉</div>
      )}
    </div>
  );
}

/**
 * The morning brief — the same narrative that leads the digest email and the
 * planning workbook, so the portal, the inbox, and the spreadsheet all say the
 * same thing. Reads the stored brief; "Rewrite" regenerates against live
 * numbers (slow — it re-runs the demand engine and the cut queue).
 */
function MorningBrief({ data, busy, onRefresh }) {
  const b = data?.brief;
  const when = data?.generated_at
    ? new Date(data.generated_at + 'Z').toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      })
    : null;

  const Section = ({ title, items, color }) =>
    (items || []).length ? (
      <div className="mt-3">
        <div className={`text-xs font-bold uppercase tracking-wide ${color}`}>{title}</div>
        <ul className="mt-1 space-y-1 text-sm text-gray-800 list-disc pl-5">
          {items.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
      </div>
    ) : null;

  return (
    <div className="bg-white rounded-lg border border-l-4 border-l-blue-600 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-500">
            Morning brief{when ? ` · ${when}` : ''}
          </div>
          <div className="text-base font-semibold text-gray-900 mt-1">
            {b?.headline || 'No brief yet — write one to get today’s read on the numbers.'}
          </div>
        </div>
        <button onClick={onRefresh} disabled={busy}
          className="shrink-0 px-3 py-2 bg-gray-100 rounded-lg hover:bg-gray-200 text-sm disabled:opacity-50">
          {busy ? 'Writing…' : b ? 'Rewrite' : 'Write brief'}
        </button>
      </div>

      {busy && (
        <div className="mt-2 text-sm text-gray-500">
          Reading the buy list, the order board, and the cut queue — about a minute.
        </div>
      )}

      {b && (
        <>
          <Section title="Buy today" items={b.buy_today} color="text-red-700" />
          <Section title="At risk" items={b.at_risk} color="text-amber-700" />
          <Section title="Changed since last brief" items={b.changed} color="text-gray-700" />
          {(b.decisions || []).length > 0 && (
            <div className="mt-3">
              <div className="text-xs font-bold uppercase tracking-wide text-amber-700">Needs your call</div>
              <ul className="mt-1 space-y-1 text-sm text-gray-800 list-disc pl-5">
                {b.decisions.map((d, i) => (
                  <li key={i}><span className="font-semibold">{d.question}</span>{d.context ? ` — ${d.context}` : ''}</li>
                ))}
              </ul>
            </div>
          )}
          <Section title="Watch" items={b.watch} color="text-gray-500" />
        </>
      )}
    </div>
  );
}

function Stat({ label, value, warn }) {
  return (
    <div className="bg-white rounded-lg border p-4">
      <div className="text-sm text-gray-500">{label}</div>
      <div className={`text-2xl font-bold ${warn ? 'text-red-600' : 'text-gray-900'}`}>{value ?? '—'}</div>
    </div>
  );
}
