# Purchase order release — BC extension handoff

The portal releases one purchase order by calling a bound action. Base
Business Central does not publish that action.

Verified against
`Apps/W1/APIV2/app/src/pages/APIV2PurchaseOrders.Page.al` (page 30066
"APIV2 - Purchase Orders"):

- The only `[ServiceEnabled]` procedure is `ReceiveAndInvoice`.
- The page is `Extensible = false`, so a page extension cannot add `Release`.
- Page 50 "Purchase Order" has a Release button, but it is not
  `[ServiceEnabled]`. Publishing page 50 as the `PurchaseOrder` web service
  (already done for Vendor Order No.) does not make release callable.

## What to publish

| Object | ID | Name |
|---|---|---|
| page | 70150 | `OPENDC API PO Release` |
| permissionset | 70151 | `OPENDC PO Release` |

API path the portal calls:

```
POST /api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrders({systemId})/Microsoft.NAV.Release
```

`{systemId}` is the purchase header system id (the `id` on api/v2.0
`purchaseOrders`). The action calls codeunit "Release Purchase Document"
`PerformManualRelease`. It does not receive or invoice.

These files are not deployed. They need to be compiled and published to
the Production company (the same extension process as
`bc-extension/picking-api`). Object IDs 70150 and 70151 were chosen above
the picking API pages (70134–70141). Confirm they are still free in
`Upwardor_BC_Repos` before publishing. The AL has not been compiled here.

## Permissions

Assign permission set **OPENDC PO Release** to the Entra application user
the portal already uses for purchase orders. That user must also be allowed
to release a purchase order in Business Central (the same right a person
uses when they press Release on the PO card). This set does not replace
those rights.

The page does not allow insert, modify, or delete through the API. Release
goes through the codeunit, which writes the purchase header itself. If a
compile or a call complains that the page is not editable, set
`ModifyAllowed = true` and publish again. Do not add a receive or invoice
action to this page.

Until the page is published, the portal returns HTTP 502 and names this
page. It does not fall through to receive or invoice.

If the page is published under a different publisher or group, set
`PO_RELEASE_BC_API_URL` to the prefix up to but not including
`/companies(...)`.
