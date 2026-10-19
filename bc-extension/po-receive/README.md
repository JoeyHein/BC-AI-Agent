# Purchase order Receive action

The portal receives a released purchase order through the standard API for
quantities, then posts with the bound action on this page. The standard
`purchaseOrders` action is `receiveAndInvoice`. This page does not publish
that action.

## What Joey publishes

1. Confirm object IDs **70910** and **70911** are free in the Business Central application.
2. Add `OPENDCPurchaseOrderReceive.API.al` to the extension that already deploys to production and publish it.
3. Assign permission set **OPENDC PO Receive** to the Business Central user behind the portal app registration, unless that user already has permission to post purchase receipts and to execute this page.
4. Web Services: publish **page 50** (Purchase Order) with service name `PurchaseOrder`, if it is not already published for vendor acknowledgements. The portal writes `Vendor_Shipment_No` (Vendor Shipment No., the packing slip) on that page.
5. Do not add a `receiveAndInvoice` action for the portal. The portal refuses any receive action whose name contains `invoice`.

After publish, this URL must answer (204 on success):

```
POST https://api.businesscentral.dynamics.com/v2.0/{tenant}/Production/api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReceives({purchaseOrderId})/Microsoft.NAV.receive
```

`purchaseOrderId` is the same GUID as `purchaseOrders({id})` on api/v2.0.

The action sets **Receive = true** and **Invoice = false**, then runs `Purch.-Post`.

## Release action

`OPENDCPurchaseOrderRelease.API.al` is a separate page. It does not add a procedure to the receive entity.

1. Confirm object IDs **70912** (page) and **70913** (permission set) are free.
2. Publish `OPENDCPurchaseOrderRelease.API.al` with the receive page.
3. Assign permission set **OPENDC PO Release** to the same Business Central user. That set executes codeunit **Release Purchase Document**. The user still needs permission to modify purchase headers and lines.
4. Do not add a `reopen` action. The portal refuses any release action whose name is not `release`, and any name that contains `reopen` or `invoice`, before it sends HTTP.

The portal POSTs the standard action first:

```
POST .../api/v2.0/companies({companyId})/purchaseOrders({id})/Microsoft.NAV.release
```

On 404 only, it POSTs this page once:

```
POST https://api.businesscentral.dynamics.com/v2.0/{tenant}/Production/api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReleases({purchaseOrderId})/Microsoft.NAV.release
```

The procedure calls `Release Purchase Document.PerformManualRelease`. A 500 is not retried. This AL has not been compiled here.
