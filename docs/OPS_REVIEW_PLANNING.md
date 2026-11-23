# Ops review — late orders, supplier dates, customer drafts, packing slips

Four changes from the weekly ops review. None of them email a customer or a supplier on their own. Business Central is patched only on the purchase-order line field `expectedReceiptDate`, and only when that write is turned on.

## 1. Morning planning email

The 04:00 planning email no longer counts material-short orders as "behind". The subject is the number of **late** sales orders among those **not fully shipped**.

A sales order is in that count when outstanding quantity is still greater than zero (quantity minus shipped or invoiced, ignoring freight and other non-stock lines) and the status is not invoiced, shipped, cancelled, or closed, and either:

- the customer's requested date or promised date is already past, or
- a linked supplier PO's expected receipt date, plus `PLANNING_INTERNAL_LEAD_DAYS` Alberta business days (default **3**), lands after the customer's requested date.

The email and the workbook tabs **Late Orders** and **Supplier Flags** list the sales order, customer, requested date, and the reason (including the supplier date and PO). Placeholder expected dates — the same date on three or more open POs, such as a shared Nov 3 — are not a supplier date.

The workbook's red/amber/green material watchlist is unchanged. It is not the late count.

## 2. Supplier confirmation tracking

Parsed, without a model call:

- Upwardor S-ORD acknowledgements (upwardor.com), including `PO-001107` and `PO 1107`
- Elton Manufacturing confirmations
- Upwardor / Michael open-order lists (xlsx, csv, or pasted lines)

The supplier's own order number is stored on `supplier_confirmations`. Every date decision is a row in `supplier_date_changes`.

An open PO (not Draft, quantity still to receive) is flagged **3 Alberta business days** after it was sent when it has no confirmation or no real expected date. Flags show in the planning email and on **Planning Flags** (`/ops-dispatch`).

| Variable | Default | What Joey turns on |
|---|---|---|
| `SUPPLIER_CONFIRM_INTAKE_ENABLED` | `false` | Scheduled mailbox poll. `POST /api/admin/ops-dispatch/supplier-confirmations/run` works either way. |
| `SUPPLIER_CONFIRM_BC_WRITE` | `false` | PATCH `expectedReceiptDate` on outstanding lines of the matched PO. Off means the date is stored and logged as `held`. |
| `SUPPLIER_CONFIRM_LOOKBACK_HOURS` | `72` | How far back each poll looks. |
| `PLANNING_INTERNAL_LEAD_DAYS` | `3` | Business days added to the supplier date when deciding lateness. |

The run endpoint takes `write_bc` (default `false`). Passing `true` is the same patch, still only `expectedReceiptDate`, and it is logged.

## 3. Customer update when a date moves

When a newly stored supplier date pushes an open sales order past the customer's requested date, a short draft is queued on `ops_outbound_messages` (`kind=customer_update`, `status=pending`). The order tracker approval button is still the only way that email goes out. This job never calls send.

Seeded draft: **O'Regan, SO-001295, expected 2026-12-04, PO-000959 and PO-001049.** It has no recipient until someone adds one. Approving it without an address is refused by the existing tracker.

## 4. Packing slips

When a sales shipment is posted, the portal can build a PDF (sales order, customer PO, lines shipped, backorders, Open Distribution, Bay 2, 125 Lockwood St NE, Redcliff AB) and queue it. The PDF route is for printing into the box.

| Variable | Default | What Joey turns on |
|---|---|---|
| `PACKING_SLIP_ENABLED` | `false` | Scheduled check of posted shipments. `POST /api/admin/ops-dispatch/packing-slips/run` works either way and still queues drafts. |
| `PACKING_SLIP_AUTO_SEND` | `false` | Email the PDF to the customer contact without an approval click. Leave this off. |
| `PACKING_SLIP_LOOKBACK_DAYS` | `14` | How recent a shipment must be. |

`POST /api/admin/ops-dispatch/packing-slips/{id}/approve` sends that one slip. Reject does not email.

## Migration

`g2h3i4j5k6l7` creates `supplier_confirmations`, `supplier_confirmation_sources`, `supplier_date_changes`, and `packing_slips`, and inserts the O'Regan draft when `ops_outbound_messages` already exists.

```bash
cd backend && python -m alembic upgrade head
```

Production runs that upgrade from `scripts/deploy.sh` after `git push origin main`. No Business Central permission change is required. The expected-receipt write uses the existing purchase-order line API.
