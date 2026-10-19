# Receiving and releasing purchase orders

The assistant (the staff service key in `OPENDC_PORTAL_SERVICE_KEY`) can release one unreleased purchase order, then list it, read outstanding quantity, set Qty. to Receive, and post **Receive only**.

The key cannot post an invoice, delete a PO, or reopen a released PO. Draft purchase-order line edits and the requested-receipt date routes are unchanged. Those still refuse anything that is not Draft.

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

A new key gets `purchasing:receive` and `purchasing:release` with the other automation scopes. The deploy migrations add those scopes to existing keys that already have `purchasing:read`, including the assistant key. That grant is the default. Read routes stay on `purchasing:read`.

There is no invoice route, no delete route, and no reopen route.

## Releasing one draft purchase order

The purchase order page shows an unreleased order as **Open**. The API calls that same order **Draft**. A released order is **Released** on the page and **Open** on the API. This route releases API status Draft only.

```
POST /api/admin/purchasing/draft-pos/PO-000962/release
```

Scope: `purchasing:release`.

`962` is accepted as `PO-000962`. A GUID works too. The purchase order number in the path is the one order that can be released. There is no route that releases every draft.

An empty body is a preview. `{}` is a preview. `dry_run` defaults to **true**.

```json
{ "dry_run": true }
```

The preview returns `bc_po_number`, `vendor_number`, `vendor_name`, `status`, `bc_page_status` (Draft on the API is Open on the page), `lines` (item, quantity, direct unit cost, amount), `totals`, and `ship_to`. Nothing is written in Business Central.

To release that one order, name it in the path and send `"dry_run": false`. If the body also includes `po_number`, it must be the same order (`962`, `PO-000962`, or that order's GUID). A different number is 400 and does not call Business Central.

```json
{ "dry_run": false, "po_number": "PO-000962" }
```

- API status Draft is released. Afterward the API status is Open (the page says Released).
- API status Open is already released and returns 422. The release action is not called.
- In Review (pending approval) returns 422.
- A missing PO is 404.
- The call is not retried. A 5xx may mean Business Central released the order and the response was lost. Check the order before sending it again.

## Release audit

Every preview, rejection, and release is a row in `purchase_release_audits` (a sibling of `purchase_receipt_audits`):

| Column | What it stores |
| --- | --- |
| `actor_name`, `actor_email` | Who. A service key is stored under the key's name. |
| `service_key_name` | The key name when the caller was the assistant. |
| `po_number`, `po_id` | The one purchase order named in the path. |
| `vendor_number`, `vendor_name` | The vendor on that order. |
| `status_before`, `status_after` | API status before the call, and after a release. |
| `ship_to`, `totals`, `lines` | The preview that was shown. |
| `dry_run`, `released`, `outcome` | `dry_run`, `released`, `rejected`, or `bc_error`. |

The key secret is not stored. Invoice, delete, and reopen are not outcomes.

## What has to be turned on in Business Central for release

The portal tries the standard action first:

```
POST .../api/v2.0/companies({companyId})/purchaseOrders({id})/Microsoft.NAV.release
```

That action is not in the documented purchaseOrders API (the documented action is `receiveAndInvoice`, which this portal never calls). A 404 tries the extension page once. Any other error stops. A 500 is not retried and does not fall through.

### Publish the Release action

Source: `bc-extension/po-receive/OPENDCPurchaseOrderRelease.API.al`.

1. Confirm object IDs **70912** (page) and **70913** (permission set) are free. 70910 and 70911 are the Receive page and its permission set.
2. Publish that page to the **production** environment (the portal does not target Sandbox).
3. Assign permission set **OPENDC PO Release** to the Business Central user for the portal app registration. The user also needs permission to modify purchase headers and lines. The page runs codeunit **Release Purchase Document**, procedure **PerformManualRelease**. It does not publish Reopen.

The page exposes:

```
POST /api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReleases({purchaseOrderId})/Microsoft.NAV.release
```

`purchaseOrderId` is the same GUID as the standard purchase order `id`.

`BC_PO_RELEASE_ENTITY` defaults to `purchaseOrderReleases`. `BC_PO_RELEASE_ACTION` must be `release`. A name containing `reopen` or `invoice` is refused before any HTTP request.

Until this page is published, a preview still works. A real release returns 502 and names page 70912 when both the standard action and the extension action are missing.

This AL has not been compiled in the portal repo. Compile and publish it from the extension that already deploys to production, after confirming the object IDs.
