# Upwardor order acknowledgements

Upwardor (vendor **UPW**) emails an order acknowledgement when they confirm a purchase order. The portal polls **joey@opendc.ca** and **Finance@opendc.ca**, stores the ack, shows it on the Production Schedule **Purchase Orders** sheet, and writes the ack number onto the BC purchase order.

This is a scheduled poll (same idea as invoice intake), not a Graph subscription. It does not send email.

## What gets stored

Table `vendor_order_acks` — one row per Upwardor order number (`S-ORD######`). A revised confirmation updates that row. `vendor_order_ack_sources` remembers each email attachment so the same PDF is not parsed twice.

| Sheet column | Source |
|---|---|
| Vendor Ack # | `S-ORD######` from the PDF header or filename. Subject `Order#116307` is the same digits. |
| Ack Status | Confirmed, Revised, or Cancelled |
| Ack Received | When the email arrived (shop-local date) |
| Completion Date | PDF "Completion Date" |

Our PO is read from the subject (`PO#000956`), the body, or the PDF (`P.O. No.`). Our sales order is the PDF line `TAG:SO-######`.

**Split confirmations** such as `PO#000960(2)` keep the suffix. They show on the base PO as `S-ORD… (2)` and are **not** written onto the primary PO's Vendor Order No.

Acknowledgements with an order number but no PO stay `pending`. They are not on the schedule. `GET /api/admin/vendor-acks?status=pending` lists them (staff JWT). The intake log also names them at the end of each run.

## Mail that matches

- Andrew Couture: subject `Confirmation Order#116307 / PO#000956` or `Revised Confirmation Order#… / PO#…`. Cancelled subjects (`Cancelled` / `Cancellation`) set status Cancelled.
- Manveer: freeform subject, body says "attached order confirmation" (or names an S-ORD). Each PDF is parsed on its own. Filenames containing `S-ORD`, `Acknowledgement`, or `SO-` are the usual attachments.

Parsing is deterministic (subject, body, `pdftotext`). There is no model call.

## Business Central write-back

The number purchasers see is **Vendor Order No.** on the purchase order (Purchase Header field 66). The standard API `purchaseOrders` entity does not include that field, so the portal PATCHes the published OData page:

1. In BC, open **Web Services**.
2. Publish **page 50** (Purchase Order) with service name `PurchaseOrder` (or set `VENDOR_ACK_BC_ODATA_ENTITY` to the name you used).
3. The field written is `Vendor_Order_No`.

A failed PATCH is stored on the row (`bc_write_status=failed`) and retried on the next poll. Intake still saves the acknowledgement. The latest unsuffixed ack for a PO is the one written; an older failure is not written back over a newer ack.

`pdftotext` (poppler) must be on the backend image. Without it, subject and filename still parse, and Completion Date / TAG lines are missed.

## Flags

All default **off** for the job itself, so a deploy does not read mail or touch BC until you turn it on.

| Variable | Default | Purpose |
|---|---|---|
| `VENDOR_ACK_INTAKE_ENABLED` | `false` | Scheduled poll. Admin `POST /api/admin/vendor-acks/run` works either way. |
| `VENDOR_ACK_DRY_RUN` | `false` | Store rows, do **not** PATCH BC. Use this for the first live check. |
| `VENDOR_ACK_BC_WRITEBACK` | `true` | Master switch for the BC write. Dry-run wins over this. |
| `VENDOR_ACK_INTAKE_MAILBOXES` | `joey@opendc.ca,Finance@opendc.ca` | Comma-separated. |
| `VENDOR_ACK_INTAKE_LOOKBACK_HOURS` | `72` | How far back each poll looks. Repeats are skipped. |
| `VENDOR_ACK_INTAKE_INTERVAL_MINUTES` | `20` | Clamped to 15–30. |
| `VENDOR_ACK_VENDOR_NO` | `UPW` | Vendor number stored on the row. |
| `VENDOR_ACK_BC_ODATA_ENTITY` | `PurchaseOrder` | OData service name for page 50. |
| `VENDOR_ACK_BC_ODATA_FIELD` | `Vendor_Order_No` | Field purchasers see as Vendor Order No. |

## Verify before relying on it

1. `cd backend && python -m alembic upgrade head`
2. Confirm poppler: `pdftotext -v`
3. Publish the Purchase Order web service (above). Leave `VENDOR_ACK_INTAKE_ENABLED` unset.
4. Dry-run one poll as a staff admin: `POST /api/admin/vendor-acks/run?dry_run=true`
5. `GET /api/admin/vendor-acks` — ack numbers, PO, status, completion date. `bc_write_status` should be `dry_run`. Pending rows have no PO.
6. Refresh the production schedule (or wait for the 04:30 / 12:30 / 16:30 job). Purchase Orders sheet shows Vendor Ack #, Ack Status, Ack Received, Completion Date. Split acks keep the `(2)` label. The Schedule sheet repeats the ack number and status on the sales-order row. See [PRODUCTION_SCHEDULE_RECON.md](PRODUCTION_SCHEDULE_RECON.md) before refreshing a live file — that job overwrites SharePoint.
7. When the rows look right, set `VENDOR_ACK_DRY_RUN=false` and `VENDOR_ACK_INTAKE_ENABLED=true`, restart the backend, and run once without `dry_run`. Confirm Vendor Order No. on the PO in BC. Failures stay on the row and in the backend log; they do not block the next PDF.
8. Do not mark this intake as the thing that posts or releases POs. It only fills Vendor Order No.
