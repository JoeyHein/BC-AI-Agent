# Receiving a released purchase order

Joey releases purchase orders in Business Central. After a PO is released, the assistant (the staff service key in `OPENDC_PORTAL_SERVICE_KEY`) can list it, read outstanding quantity, set Qty. to Receive, and post **Receive only**.

The key cannot release a PO, post an invoice, or delete a PO. Draft purchase-order edits and the requested-receipt date routes are unchanged. Those still refuse anything that is not Draft.

## How the assistant calls it

Send the key as `Authorization: Bearer osk_live_...` or `X-API-Key`.

Business Central's API status `Open` means the purchase order page says **Released**. Status `Draft` on the API is the unreleased order.

### List

```
GET /api/admin/purchasing/released-pos
GET /api/admin/purchasing/released-pos?outstanding_only=true
GET /api/admin/purchasing/released-pos?number=PO-000962
```

Scope: `purchasing:read`.

Each line has `ordered_quantity`, `received_quantity`, and `outstanding_quantity`. `qty_to_receive` on this read is whatever Qty. to Receive is already sitting on the order (Business Central often fills that with the full outstanding quantity). The receive call below replaces it.

### One purchase order

```
GET /api/admin/purchasing/released-pos/PO-000962
```

`962` is accepted as `PO-000962`. A GUID works too. A missing PO is 404. A PO that is not released is 422 and is not received.

### Preview, then post

```
POST /api/admin/purchasing/released-pos/PO-000962/receive
```

Scope: `purchasing:receive`.

```json
{
  "dry_run": true,
  "vendor_shipment_no": "PACK-100",
  "lines": [
    {"item_number": "PN10", "qty_to_receive": 2}
  ]
}
```

`dry_run` defaults to **true**. The preview returns the lines that would post (`receiving`), the lines whose Qty. to Receive would be cleared so they are not received (`lines_to_clear`), and `posting: "Receive"`, `invoice: false`. Nothing is written in Business Central.

To post, send the same body with `"dry_run": false`.

- `vendor_shipment_no` is the vendor packing slip. It is written to Vendor Shipment No. on the purchase order before the post. `vendor_packing_slip` is the same field. At most 35 characters.
- Identify a line with `line_id`, `sequence`, or `item_number`. If the item is on two lines, send `line_id` or `sequence`.
- `qty_to_receive` must be greater than zero and not above outstanding. A partial quantity is allowed.
- Comment lines are rejected.
- Lines omitted from `lines` are not received. Their Qty. to Receive is set to 0 before the post so Business Central's default (the full remainder) is not posted by accident.
- Qty. to Invoice on a line being received is set to 0. The post action sets Receive = true and Invoice = false.

A successful post returns `posted: true` and `bc_receipt_no` when Business Central returns the posted receipt number.

## Audit

Every preview, rejected attempt, and posted receipt is a row in `purchase_receipt_audits`:

| Column | What it stores |
| --- | --- |
| `actor_name`, `actor_email` | Who. A service key is stored under the key's name. |
| `service_key_name` | The key name when the caller was the assistant. |
| `po_number`, `po_id` | The purchase order. |
| `lines` | Line ids, items, ordered, received, outstanding, and qty to receive. |
| `vendor_shipment_no` | The packing slip. |
| `posting` | Always `Receive`. |
| `invoice` | Always false. |
| `dry_run`, `posted`, `outcome` | `dry_run`, `posted`, `rejected`, or `bc_error`. |
| `bc_receipt_no` | Posted receipt number after a successful post. |

The key secret is not stored.

## What has to be turned on in Business Central

Quantities use the API the portal already uses (`api/v2.0` `purchaseOrders` / `purchaseOrderLines`, field `receiveQuantity`). That API does **not** have a Receive-only post. The documented bound action is:

```
POST .../purchaseOrders({id})/Microsoft.NAV.receiveAndInvoice
```

That action receives **and invoices**. The portal never calls it. Calling a receive URL whose action name contains `invoice` raises before any HTTP request is sent.

### 1. Publish the Receive action

Source: `bc-extension/po-receive/OPENDCPurchaseOrderReceive.API.al`.

1. Confirm object IDs **70910** (page) and **70911** (permission set) are free.
2. Publish that page to the **production** environment (the portal does not target Sandbox).
3. Assign permission set **OPENDC PO Receive** to the Business Central user for the portal app registration, unless that user can already post purchase receipts and execute the page.

The page exposes:

```
POST /api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReceives({purchaseOrderId})/Microsoft.NAV.receive
```

`purchaseOrderId` is the same GUID as the standard purchase order `id`. The action checks the order is Released, sets Receive = true and Invoice = false, and runs codeunit **Purch.-Post**.

Override the path with `BC_PO_RECEIVE_PUBLISHER`, `BC_PO_RECEIVE_GROUP`, `BC_PO_RECEIVE_VERSION`, `BC_PO_RECEIVE_ENTITY`, or `BC_PO_RECEIVE_ACTION` only if the page was published under other names. `BC_PO_RECEIVE_ACTION` must not contain `invoice`.

Until this page is published, a preview still works. A real post returns 502 and names this page. Quantities are put back when Business Central refuses the post before it commits.

### 2. Vendor Shipment No. on page 50

The standard purchase order API does not include Vendor Shipment No. (Purchase Header field 69). The portal writes it the same way vendor acknowledgements write Vendor Order No.:

1. Web Services.
2. Page **50**, Purchase Order, service name `PurchaseOrder` (or `VENDOR_ACK_BC_ODATA_ENTITY`).
3. Field `Vendor_Shipment_No` (or `BC_PO_VENDOR_SHIPMENT_FIELD`).

If vendor acknowledgements already patch this page, no second web service is required. The field has to be on the published page.

### 3. The service key

A new key gets `purchasing:receive` with the other automation scopes. The deploy migration adds `purchasing:receive` to existing keys that already have `purchasing:read`, including the assistant key. Read routes stay on `purchasing:read`.

There is no release route, no invoice route, and no delete route for these purchase orders.
