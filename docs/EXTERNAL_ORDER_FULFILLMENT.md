# External order status, shipment, and pickup/delivery (ED-008)

Read-only surface so a customer of Open Distribution — Elevated Doors is the
first — can track its Business Central sales orders through the same API key
the quote bridge already uses. These routes do not create, ship, or confirm
anything in Business Central. They read the open sales order, its lines, and
posted sales shipments the same way the customer portal does (`salesOrders`,
`salesOrderLines`, `salesShipments`), and they read the picking extension
when it is deployed (live queue + posted picking headers) for the load method.

Auth: `X-Service-AI-Key`. The key is bound to one BC customer number
(`supplier_account_code`). Every call also sends that number as
`supplierAccountCode`. If the query value is not the key's customer, the
response is **404** `NOT_FOUND` / "Supplier account not found" — never 403.
An order (or posted shipment) whose `customerNumber` is not that customer is
**404** `NOT_FOUND` / "Order not found", including when the order exists for
someone else.

## Endpoints

| Method | Path | What it returns |
|---|---|---|
| GET | `/api/external/orders` | Open sales orders for the customer |
| GET | `/api/external/orders/{orderNumber}` | F1 status, lines, shipments, tracking, and the F2 fulfillment object |
| GET | `/api/external/orders/{orderNumber}/fulfillment` | F2 pickup/delivery schedule and confirmation only |

`{orderNumber}` is the BC document number (`SO-003132`) or the open sales
order GUID. A posted order that BC has removed from `salesOrders` is found
by document number via posted `salesShipments`. A GUID only resolves an
order that is still open.

Query (all three): `supplierAccountCode` — required, must equal the key binding.

Success envelope:

```json
{ "ok": true, "data": { } }
```

Error envelope (400, 404 from these routes, 502):

```json
{
  "ok": false,
  "error": { "code": "NOT_FOUND", "message": "Order not found", "retryable": false }
}
```

| HTTP | `error.code` | When |
|---|---|---|
| 401 | `UNAUTHORIZED` | Missing, unknown, or revoked key. Body is FastAPI's `{"detail": {"ok": false, "error": {...}}}` — same as the other `/api/external` routes. `retryable` is omitted. |
| 400 | `INVALID_REQUEST` | Missing `supplierAccountCode`, or an order number that is not a document number or GUID. |
| 404 | `NOT_FOUND` | Account does not match the key, or this customer has no such order. |
| 502 | `UPSTREAM_ERROR` | Business Central did not answer. `retryable` is true. Safe to retry; these routes only read. |

`complete: false` on the list means paging stopped early. Do not treat that
page as the full set of open orders.

## List — `GET /api/external/orders`

```json
{
  "ok": true,
  "data": {
    "customerNumber": "ED-001",
    "complete": true,
    "orders": [
      {
        "orderNumber": "SO-003132",
        "orderId": "8f1c2c3a-0000-4000-8000-000000000001",
        "externalDocumentNumber": "ED-PO-100",
        "customerNumber": "ED-001",
        "customerName": "Elevated Doors",
        "status": "Open",
        "orderDate": "2026-09-01",
        "requestedDeliveryDate": "2026-10-15",
        "currency": "CAD",
        "totalAmountIncludingTax": 1130.0,
        "fullyShipped": false,
        "shipmentMethodCode": null,
        "method": "unknown"
      }
    ]
  }
}
```

`method` on a list row is only classified from `shipmentMethodCode` (lines
are not expanded). Call the order or fulfillment endpoint for pickup vs
delivery. `status` is the Business Central sales-order status (`Draft`,
`Open`, and whatever else BC returns).

Orders are newest `orderDate` first. Rows BC returns for a different
`customerNumber` are dropped even if the filter is ignored.

## Order — `GET /api/external/orders/{orderNumber}`

```json
{
  "ok": true,
  "data": {
    "orderNumber": "SO-003132",
    "orderId": "8f1c2c3a-0000-4000-8000-000000000001",
    "customerNumber": "ED-001",
    "customerName": "Elevated Doors",
    "externalDocumentNumber": "ED-PO-100",
    "status": "Open",
    "source": "open_order",
    "orderDate": "2026-09-01",
    "requestedDeliveryDate": "2026-10-15",
    "currency": "CAD",
    "totalAmountExcludingTax": 1000.0,
    "totalTaxAmount": 130.0,
    "totalAmountIncludingTax": 1130.0,
    "fullyShipped": false,
    "outstandingKnown": true,
    "fulfillmentStatus": "partially_shipped",
    "shipmentMethodCode": null,
    "shipTo": {
      "name": "Elevated Doors",
      "contact": "Joey",
      "addressLine1": "1 Yard Rd",
      "addressLine2": null,
      "city": "Calgary",
      "state": "AB",
      "postCode": "T2P 1A1",
      "country": "CA"
    },
    "lines": [
      {
        "sequence": 10000,
        "lineType": "Item",
        "itemNo": "PN65-18405-0800",
        "description": "Section",
        "quantity": 4,
        "shippedQuantity": 2,
        "outstandingQuantity": 2,
        "unitOfMeasureCode": "PCS"
      }
    ],
    "shipments": [
      {
        "shipmentId": "aa000000-0000-4000-8000-000000000002",
        "shipmentNumber": "SS-000451",
        "orderNumber": "SO-003132",
        "externalDocumentNumber": "ED-PO-100",
        "shipmentDate": "2026-09-20",
        "postingDate": "2026-09-20",
        "trackingNumber": "1Z999",
        "carrier": "UPS",
        "shipToName": "Elevated Doors",
        "shipTo": {
          "name": "Elevated Doors",
          "contact": null,
          "addressLine1": "1 Yard Rd",
          "addressLine2": null,
          "city": "Calgary",
          "state": "AB",
          "postCode": "T2P 1A1",
          "country": "CA"
        }
      }
    ],
    "fulfillment": { }
  }
}
```

`fulfillment` is the same object the fulfillment endpoint returns.

`source` is `open_order` or `posted_shipment`. `posted_shipment` means the
open sales order is gone and the header was rebuilt from posted shipments:
`status` is `Posted`, `outstandingKnown` is false, `fulfillmentStatus` is
`fully_shipped`, and `lines` is empty. Line-level outstanding quantity is
only known while the order is still open (`outstandingKnown: true`).

`fulfillmentStatus`:

| Value | Meaning |
|---|---|
| `not_shipped` | No item quantity shipped and no posted shipment |
| `partially_shipped` | Some item quantity has shipped, or a posted shipment exists while item quantity is still outstanding |
| `fully_shipped` | Item quantity is shipped, BC `fullyShipped` is true, or the order is posted |

Comment lines are not counted. The header flag `fullyShipped` is unreliable
on its own; the detail endpoint prefers line `quantity` / `shippedQuantity`.

`trackingNumber` and `carrier` are filled from the posted shipment when
Business Central sends `packageTrackingNo`, `trackingNumber`,
`shippingAgentCode`, or the same under the other names listed in
`external_order_status_service`. The standard api/v2.0 `salesShipments`
entity often omits them; the fields are then `null`. This route does not
invent a tracking number.

## Fulfillment — `GET /api/external/orders/{orderNumber}/fulfillment`

```json
{
  "ok": true,
  "data": {
    "orderNumber": "SO-003132",
    "customerNumber": "ED-001",
    "method": "pickup",
    "methodSource": "order_comment",
    "scheduledDate": "2026-10-15",
    "shipmentDate": "2026-09-20",
    "confirmed": true,
    "confirmation": "picked_up",
    "fulfillmentStatus": "fully_shipped",
    "shipTo": { },
    "picking": {
      "available": true,
      "queueStatus": null,
      "pickingDate": null,
      "shipmentDate": "2026-09-20",
      "loadMethod": "Pickup",
      "posted": true,
      "shipmentNo": "SS-000451"
    }
  }
}
```

`scheduledDate` is the sales order `requestedDeliveryDate`. `shipmentDate`
is the earliest posted shipment date, otherwise the picking queue /
posted-header date.

`method`:

| Value | How it is chosen |
|---|---|
| `pickup` | A **Comment** line containing "customer pickup" or starting with `** PICKUP` (the configurator banner), or a shipment-method / picking `loadMethod` that says pickup. Item text such as "CENTER PICKUP KIT" is hardware and is ignored. |
| `delivery` | Shipment-method code or picking `loadMethod` contains "deliv". |
| `unknown` | BC did not say. A ship-to address is not treated as delivery, because pickup orders still carry the customer address. |

`methodSource` is `order_comment`, `shipment_method`, `load_method`, or `null`.

`confirmation`:

| Value | `confirmed` | Meaning |
|---|---|---|
| `unscheduled` | false | Draft (or otherwise unconfirmed) and no requested delivery date |
| `scheduled` | false | A requested delivery date is set, and the order is not yet confirmed or shipped |
| `confirmed` | true | BC status is Open, Released, Pending Approval, or Pending Prepayment, and it has not shipped |
| `partially_fulfilled` | true | Some quantity has shipped |
| `picked_up` | true | Fully shipped and `method` is pickup |
| `delivered` | true | Fully shipped and `method` is delivery |
| `fulfilled` | true | Fully shipped and `method` is unknown |

`picking.available` is false when the picking extension is not deployed or
the read failed. The order and shipment data still return. `picking.posted`
means a posted picking header exists for this sales order and customer.
`queueStatus` is the live queue status while the order is on the floor.

## Example

Do not put a real key in the repo or in shell history you commit.

```bash
BASE="${PORTAL_BASE_URL:-https://portal.opendc.ca}"

curl -fsS \
  -H "X-Service-AI-Key: ${SERVICE_AI_KEY}" \
  "$BASE/api/external/orders?supplierAccountCode=${SUPPLIER_ACCOUNT_CODE}"

curl -fsS \
  -H "X-Service-AI-Key: ${SERVICE_AI_KEY}" \
  "$BASE/api/external/orders/SO-003132?supplierAccountCode=${SUPPLIER_ACCOUNT_CODE}"

curl -fsS \
  -H "X-Service-AI-Key: ${SERVICE_AI_KEY}" \
  "$BASE/api/external/orders/SO-003132/fulfillment?supplierAccountCode=${SUPPLIER_ACCOUNT_CODE}"
```

## Compatibility

These routes are new files plus BC client helpers appended after the existing
picking methods, and a router include next to the other `/api/external`
routers. They do not change invoice-line paging or the staff sales routes.
