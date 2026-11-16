# Purchase order receive — BC extension handoff

The portal receives selected lines on one purchase order by calling a bound
action. Base Business Central does not publish a receive-only action.

Verified against
`Apps/W1/APIV2/app/src/pages/APIV2PurchaseOrders.Page.al` (page 30066
"APIV2 - Purchase Orders"):

- The only `[ServiceEnabled]` procedure is `ReceiveAndInvoice`.
- That procedure sets `Receive := true` and `Invoice := true`, then posts.
  A combined post invoices the quantity just received.
- The page is `Extensible = false`, so a page extension cannot add `Receive`.
- Setting `receiveQuantity` on `purchaseOrderLines` and calling
  `receiveAndInvoice` still invoices. Do not use that action.
- Page 50 "Purchase Order" can post from the client, but its buttons are not
  `[ServiceEnabled]`. Publishing page 50 as the `PurchaseOrder` web service
  (already done for Vendor Order No.) does not make a receipt callable.

This page calls codeunit "Purch.-Post" with `Receive = true` and
`Invoice = false`. It does not call a mail codeunit. Lines left out of the
request are posted with Qty. to Receive = 0, so a partial receipt does not
receive the rest of the order. Qty. to Invoice is not edited here.
Purch.-Post ignores it when Invoice is false, and a later invoice in the
Business Central client can still use the received quantity.

An order in status Open (the purchaseOrders API calls this Draft) is
released with codeunit "Release Purchase Document" before the receipt,
because posting requires Released. Pending Approval and Pending Prepayment
are refused. The release is the same codeunit the Release button uses. It
does not send email.

The same vendor shipment number on the same order returns the existing
posted receipt and does not post again. That number is Purchase Header
field "Vendor Shipment No." (the packing slip), copied onto the posted
receipt. It is stored as uppercase, 35 characters.

## What to publish

Compile these objects into the **same extension** as page 70150
`OPENDC API PO Release`. Both use API publisher `opendc`, group
`purchasing`, version `v1.0`. A second app cannot own that route.
If the release app is already in Production, ship this as an upgrade of
that app. If neither page is published yet, publish them together.

| Object | ID | Name |
|---|---|---|
| page | 70152 | `OPENDC API PO Receive` |
| permissionset | 70153 | `OPENDC PO Receive` |

Confirm 70152 and 70153 are free in `Upwardor_BC_Repos` before publishing.
The release objects are 70150 and 70151. The picking API pages are
70134–70141. The AL has not been compiled here.

API paths the portal calls (`{systemId}` is the purchase header system id,
the `id` on api/v2.0 `purchaseOrders`):

```
POST /api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReceiptPosts({systemId})/Microsoft.NAV.FindReceipt
{"vendorShipmentNo": "PACK-1058"}

POST /api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReceiptPosts({systemId})/Microsoft.NAV.Receive
{"vendorShipmentNo": "PACK-1058", "linesJson": "[{\"lineNo\":10000,\"qty\":30}]"}
```

`lineNo` is Purchase Line "Line No." (api/v2.0 `sequence`, usually 10000,
20000, …). The response field `postedReceiptNo` is the posted receipt
number. `invoiced` is false.

## Permissions

Assign permission set **OPENDC PO Receive** to the Entra application user
the portal already uses. That user must also be allowed to post a purchase
receipt in the Business Central client (item ledger entry and the other
tables codeunit "Purch.-Post" writes). This set does not replace those
rights and does not add an invoice action.

The page does not allow insert, modify, or delete through the API. The
action updates the purchase lines and then posts. If a compile or a call
complains that the page is not editable, set `ModifyAllowed = true` and
publish again. Do not add an invoice action.

Until the page is published, the portal returns HTTP 502 and names this
page. It does not call `receiveAndInvoice`.

If the page is published under a different publisher, group, or version,
set `PO_RECEIVE_BC_API_URL` to the prefix up to but not including
`/companies(...)`.

## Locations that require a warehouse receipt

If the line's location has warehouse receive required, Purch.-Post refuses
a direct receipt and tells you warehouse handling is required. This page
does not create a warehouse receipt. Post those orders the way the
warehouse already does, or turn off require-receive for that location if
a direct receipt is how purchasers receive it today.

## Not compiled

No AL compiler was available here. Build the extension before publishing
to Production (not Sandbox).
