# Release one purchase order

Staff, or a service key that was given `purchasing:release_po`, can release
a single Business Central purchase order. Creating a draft, editing lines,
setting the requested receipt date, and saving an Outlook review draft do
not release. Nothing releases a PO unless this call is made, and the body
sets `confirm` to true.

## What “release” means

In the purchaseOrders API:

| API `status` | Business Central document status | This endpoint |
|---|---|---|
| `Draft` | Open (not released) | Can be released |
| `Open` | Released | HTTP 409, nothing is changed |
| `Released` | Released | HTTP 409, nothing is changed |
| `In Review` | Pending approval | HTTP 422, nothing is changed |

A successful release leaves the order **Released** in Business Central. The
API then reports that as **Open**. The response says both, so an Open status
after this call is the released order, not a failure.

The call does not receive the order, invoice it, or send email.

## Auth

Staff JWT with **Purchase orders → Create and send** (`purchase_orders.send`).
A login that can only edit drafts cannot release.

Or a staff service key whose scopes include `purchasing:release_po`. That
scope is not on the automation preset and is not added when a key is created
with no scope list. Grant it on the assistant’s key only:

```bash
curl -sS -X POST "$BASE/api/admin/service-keys" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Assistant PO release","scopes":["automation","purchasing:release_po"]}'
```

`automation` is the existing allow-list. `purchasing:release_po` is the extra.
Copy the plaintext once.

## Call

```bash
# Check only. Does not release.
curl -sS -X POST "$BASE/api/admin/purchasing/draft-pos/PO-000962/release" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'

# Release this one PO.
curl -sS -X POST "$BASE/api/admin/purchasing/draft-pos/PO-000962/release" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm": true, "approved_by": "joey@opendc.ca"}'
```

`PO-000962`, `962`, and the Business Central system id are accepted. One PO
per call.

| | |
|---|---|
| Released | `200` `{ released: true, api_status_before: "Draft", api_status_after: "Open", bc_document_status: "Released", ... }` |
| Dry run, checks passed | `200` `{ dry_run: true, would_release: true, released: false, bc_called: false }` |
| Dry run, checks failed | `200` `{ dry_run: true, would_release: false, reasons: [...] }` |
| Comment-only, customer leak, or missing confirm | `422` `{ detail: { message, reasons: [{ code, message }] } }` |
| Already released | `409` `{ detail: { noop: true, message } }` |
| Unknown PO | `404` |
| Release page not published in BC, or BC rejects the action | `502` |

`confirm` must be the JSON boolean `true`. `approved_by` is the person who
said to release this order (name or email). The signed-in user is stored
separately. Dry run does not need either field.

## Checks before release

A real release is refused with HTTP 422 when any of these fail. Dry run
returns the same reasons and does not call Business Central.

1. **Item quantity.** At least one line with type Item and quantity greater
   than zero. Comment-only orders are refused (`no_item_quantity`).
2. **Customer info.** Same rule as PR #61 (`vendor_may_see_customer_info`):
   only Upwardor (UPW), Elton (ELT), and Nice/Micanan may carry the customer
   name, the customer’s PO, the job, or ship-to customer text. Other vendors
   are refused (`customer_info_on_vendor_po`). Our sales-order number
   (`Built from SO-######`) is allowed. The check also reads the ship-to
   header fields. #61 is not merged yet; this branch includes the same
   `po_customer_disclosure.py` module so the check works on its own. If #61
   merges first, keep one copy of that file.
3. **Existing draft validation.** Buy-complete, companion, and price
   warnings from `GET .../draft-pos/{po}/validate` are returned as
   `warnings` and do **not** block. An issue that validator marks
   `severity: error` does block. Today those rules are warnings.
4. **Vendor acknowledgement price.** Not checked. Acknowledgements store
   the vendor order number, status, and completion date. They do not store
   a quoted unit price, so there is nothing to compare to the PO line.
   The response includes `vendor_quote_price_check.applied: false`.

Every outcome except “PO not found” writes an `audit_trail` row: who
(`actor` and `approved_by`), when, the PO number, and the validation
result. The action name is `purchase_order_release_released`,
`purchase_order_release_dry_run`, `purchase_order_release_refused`, or
`purchase_order_release_noop`.

## Business Central setup

The standard API cannot release a purchase order.

Verified on page 30066 “APIV2 - Purchase Orders”
(`APIV2PurchaseOrders.Page.al`): the only `[ServiceEnabled]` procedure is
`ReceiveAndInvoice`, and the page is `Extensible = false`. Page 50’s
Release button is not `[ServiceEnabled]`. The `PurchaseOrder` web service
already published for Vendor Order No. does not release.

Publish the pages in `bc-extension/purchase-order-release/` to **Production**
(not Sandbox):

| Object | ID | Name |
|---|---|---|
| page | 70150 | OPENDC API PO Release |
| permissionset | 70151 | OPENDC PO Release |

Confirm those object IDs are free in `Upwardor_BC_Repos` before publishing.
The AL here has not been compiled.

The portal then calls:

```
POST {BC}/api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrders({systemId})/Microsoft.NAV.Release
```

`{systemId}` is the purchase header system id (`id` on api/v2.0
purchaseOrders). The action runs codeunit “Release Purchase Document”,
`PerformManualRelease`. It does not receive or invoice.

Assign permission set **OPENDC PO Release** to the Entra application user
the portal already uses, in addition to the rights that user needs to
release a PO in the Business Central client. Until the page is published,
this endpoint returns 502 and names the page. It does not call
`receiveAndInvoice`.

If the page is published under another publisher or group, set
`PO_RELEASE_BC_API_URL` to the prefix up to but not including
`/companies(...)`.

No database migration. The audit row uses the existing `audit_trail` table.
