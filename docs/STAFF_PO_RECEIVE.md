# Receive lines on one purchase order

Staff with **Purchase orders → Create and send**, or a service key that was
given `purchasing:receive_po`, can post a receipt for specific lines and
quantities on one Business Central purchase order. The receipt can be
partial. The order is not invoiced and the vendor is not emailed.

Creating a draft, editing lines, setting the requested receipt date, saving
an Outlook review draft, and releasing a PO do not receive. Nothing is
received unless this call is made and the body sets `confirm` to true.

## What “receive” means

| API `status` | Business Central document status | This endpoint |
|---|---|---|
| `Draft` | Open (not released) | Released, then received |
| `Open` | Released | Received |
| `Released` | Released | Received |
| `In Review` | Pending approval | HTTP 422, nothing is posted |

Posting a receipt requires the order to be Released. A Draft is released
inside the receive action, with the same “Release Purchase Document”
codeunit the Release button uses. That release does not send email. The
portal release checks (customer text on the PO, comment-only) are not
repeated here: those guard sending a PO to a vendor. This call does not
send the PO.

Lines you do not list are posted with quantity to receive = 0, so the rest
of the order stays outstanding. `line_no` is the purchase line number, the
`sequence` field on `GET /api/bc/purchase-orders/{po}` (usually 10000,
20000, …).

A successful call leaves a posted purchase receipt. It does not create a
posted purchase invoice. The standard `receiveAndInvoice` action is not
called. That action sets Invoice as well as Receive, and Business Central
then invoices the quantity just received.

## Auth

Staff JWT with **Purchase orders → Create and send** (`purchase_orders.send`).
The Purchasing, Manager, Admin, and Owner presets have it. Sales, Viewer,
and Warehouse do not. A login that can only view a PO, or only edit a
draft, cannot receive.

Or a staff service key whose scopes include `purchasing:receive_po`. That
scope is not on the automation preset and is not added when a key is
created with no scope list. The Settings page creates an automation key, so
it cannot receive. Grant the scope on the key stored as
`OPENDC_PORTAL_SERVICE_KEY` (that variable is not in this repo; it is the
secret the assistant sends). There is no way to add a scope to an existing
key. Create a new key that keeps the automation scopes and adds this one,
put the new plaintext in that variable, then revoke the old key:

```bash
curl -sS -X POST "$BASE/api/admin/service-keys" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Portal service","scopes":["automation","purchasing:receive_po"]}'
```

`automation` is the existing allow-list. `purchasing:receive_po` is the extra.
Copy the plaintext once.

Reading the PO still needs `purchasing:read`, which `automation` already includes.

## Call

```bash
# Check only. Does not release and does not receive.
# Use the line's sequence from GET /api/bc/purchase-orders/PO-001058.
curl -sS -X POST "$BASE/api/bc/purchase-orders/PO-001058/receive" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true, "lines": [{"line_no": 10000, "qty": 30}]}'

# Receive 30 on that line. PACK-1058 is the vendor's packing slip.
curl -sS -X POST "$BASE/api/bc/purchase-orders/PO-001058/receive" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm": true, "vendor_shipment_no": "PACK-1058", "lines": [{"line_no": 10000, "qty": 30}]}'
```

`PO-001058`, `1058`, and the Business Central system id are accepted. One PO
per call. `confirm` must be the JSON boolean `true`. Dry run does not need it.

| | |
|---|---|
| Received | `200` `{ posted: true, invoiced: false, emailed: false, posted_receipt_no, lines, ... }` |
| Same packing slip again | `200` `{ posted: false, idempotent: true, posted_receipt_no }` |
| Dry run, checks passed | `200` `{ dry_run: true, would_post: true, posted: false, bc_post_called: false }` |
| Dry run, quantity too high | `200` `{ dry_run: true, would_post: false, reasons: [{ code: "qty_exceeds_outstanding" }] }` |
| Missing confirm, unknown line, or quantity over outstanding | `422` |
| Pending approval | `422` `{ reasons: [{ code: "not_receivable_status" }] }` |
| Unknown PO | `404` |
| Receive page not published in BC, or BC rejects the post | `502` |

`vendor_shipment_no` is optional. When it is set, it is the idempotency key:
a second call with the same value on the same PO returns the receipt from
the first call and does not post. Business Central stores it in uppercase,
35 characters, as Vendor Shipment No. on the receipt. Omit it and each
confirmed call posts another receipt.

## One-line test

On PO-001058, `GET` the order, then dry-run qty 30 on the item line's
`sequence` (only if outstanding is at least 30), then repeat with
`confirm: true` and a new `vendor_shipment_no`; the response
`posted_receipt_no` should be a posted receipt, and the order should have
no new posted purchase invoice.

## Business Central setup

The standard API cannot receive without invoicing.

Verified on page 30066 “APIV2 - Purchase Orders”: the only
`[ServiceEnabled]` procedure is `ReceiveAndInvoice`, which sets both
Receive and Invoice, and the page is `Extensible = false`. Setting
`receiveQuantity` and calling that action still invoices.

Publish the pages in `bc-extension/purchase-order-receive/` to **Production**
(not Sandbox), in the **same extension** as page 70150 “OPENDC API PO
Release”. Both use publisher `opendc`, group `purchasing`, version `v1.0`.
A second app cannot own that API route. If the release app is already
published, ship this as an upgrade. If neither is published, publish them
together.

| Object | ID | Name |
|---|---|---|
| page | 70152 | OPENDC API PO Receive |
| permissionset | 70153 | OPENDC PO Receive |

Confirm those object IDs are free in `Upwardor_BC_Repos` before publishing.
The AL here has not been compiled.

The portal then calls:

```
POST {BC}/api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReceiptPosts({systemId})/Microsoft.NAV.Receive
```

`{systemId}` is the purchase header system id (`id` on api/v2.0
purchaseOrders). The body is `vendorShipmentNo` and `linesJson`
(`[{"lineNo":10000,"qty":30}]`). The action runs codeunit “Purch.-Post”
with Receive true and Invoice false. It does not email.

Assign permission set **OPENDC PO Receive** to the Entra application user
the portal already uses, in addition to the rights that user needs to post
a receipt in the Business Central client (item ledger and the other tables
Purch.-Post writes). Until the page is published, this endpoint returns 502
and names the page. It does not call `receiveAndInvoice`.

If a location requires warehouse receive, Business Central refuses a direct
receipt. This page does not create a warehouse receipt.

If the page is published under another publisher or group, set
`PO_RECEIVE_BC_API_URL` to the prefix up to but not including
`/companies(...)`.

No database migration. The audit row uses the existing `audit_trail` table.
The action name is `purchase_order_receive_received`,
`purchase_order_receive_idempotent`, `purchase_order_receive_dry_run`,
`purchase_order_receive_refused`, or `purchase_order_receive_bc_unavailable`.
Each row records who called, the PO number, the lines and quantities, the
packing slip, and the posted receipt number.
