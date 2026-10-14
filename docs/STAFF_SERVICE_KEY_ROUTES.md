# Staff service key routes

A staff service key (`Authorization: Bearer osk_live_...` or `X-API-Key`) can call only the routes below. Anything else is refused with `This service key is not allowed to call this route.`

A new key gets every scope. These reads use scopes the automation key already has (`quotes:read`, `orders:read`, `purchasing:read`, `inventory:read`), so an existing key can call them without being recreated.

Writes that create, convert, post, ship, or email a Business Central document are not on this list, except the Draft purchase-order edits that were already allowed.

## Business Central reads

| Scope | Route | What it returns |
| --- | --- | --- |
| `quotes:read` | `GET /api/bc/sales-quotes` | Paged quote list. `search` matches the quote number. `skip` or `offset` pages. `top` defaults to 50. Newest quote number first. |
| `quotes:read` | `GET /api/bc/sales-quotes/SQ-003132` | Header (customer, valid-until, status, totals) and every line, including comment lines. `3132` is accepted as `SQ-003132`. |
| `orders:read` | `GET /api/bc/sales-orders/SO-000857` | Sales order header and every line. |
| `purchasing:read` | `GET /api/bc/purchase-orders/PO-000962` | Purchase order header and every line, any status. |
| `quotes:read` | `GET /api/bc/customers` | Customers, including `bc_price_group`. `search` matches name, email, number, or price group. |
| `quotes:read` | `GET /api/bc/customers/ABES` | One customer by BC number, including price group. |
| `quotes:read` | `GET /api/admin/customers/bc-customers` | Cached BC customers for the portal picker, including price group, pricing tier, and customer number. |
| `inventory:read` | `GET /api/bc/items` | Item search (`search` is required) with unit price, unit cost, and on-hand quantity. |
| `inventory:read` | `GET /api/bc/items/PN10` | One item by number, with unit price, unit cost, and on-hand quantity. |
| `purchasing:read` | `GET /api/bc/vendors` | Vendor cards. |
| `purchasing:read` | `GET /api/admin/purchasing/vendors` | Vendor number and name. |
| `orders:read` | `GET /api/bc/sales-invoices/PS-100001` | Posted sales invoice header and lines. A Draft invoice is not returned. |
| `purchasing:read` | `GET /api/bc/purchase-invoices/PI-100001` | Posted purchase invoice header and lines. A Draft invoice is not returned. |
| `quotes:read` | `GET /api/bc/sales-price-lines` | Sales price list lines. Query: `item_no`, `source_type` (0 all customers, 1 customer, 2 price group), `source_no`, `qty`, `as_of`. |
| `quotes:read` | `GET /api/door-config/load-quote/SQ-003132` | Reload a live quote into the door configurator. |
| `quotes:read` | `GET /api/metrics/quoting` | Quoting pipeline analytics. |

## KPI dashboard

These need all four read scopes together: `orders:read`, `purchasing:read`, `quotes:read`, and `inventory:read`. A key that has only some of them is refused. The routes are read-only.

| Scope | Route | What it returns |
| --- | --- | --- |
| `orders:read`, `purchasing:read`, `quotes:read`, and `inventory:read` | `GET /api/kpi/dashboard` | Saved financial and operations KPIs for one month (`month` as `YYYY-MM`, or the current month). |
| `orders:read`, `purchasing:read`, `quotes:read`, and `inventory:read` | `GET /api/kpi/dashboard/purchasing` | Purchasing and vendor KPIs only. |
| `orders:read`, `purchasing:read`, `quotes:read`, and `inventory:read` | `GET /api/kpi/dashboard/sales` | Sales KPIs only. |
| `orders:read`, `purchasing:read`, `quotes:read`, and `inventory:read` | `GET /api/kpi/dashboard/financial` | Financial KPIs only. |
| `orders:read`, `purchasing:read`, `quotes:read`, and `inventory:read` | `GET /api/kpi/dashboard/operations` | Operations KPIs only. |

## Orders

| Scope | Route |
| --- | --- |
| `orders:read` | `GET /api/orders` |
| `orders:read` | `GET /api/orders/legacy` |
| `orders:read` | `GET /api/orders/stats/pipeline` |
| `orders:read` | `GET /api/orders/1` |
| `orders:read` | `GET /api/orders/1/production-orders` |
| `orders:read` | `GET /api/orders/1/spring-production-orders` |
| `orders:read` | `GET /api/orders/1/shipments` |
| `orders:read` | `GET /api/orders/1/invoices` |
| `orders:read` | `GET /api/orders/bc/orders` |

## Inventory and catalog

The same inventory paths are also accepted without the `/api` prefix.

| Scope | Route |
| --- | --- |
| `inventory:read` | `GET /api/inventory/levels` |
| `inventory:read` | `GET /api/inventory/item/PN10` |
| `inventory:read` | `GET /api/inventory/item/PN10/movements` |
| `inventory:read` | `GET /api/inventory/categories` |
| `inventory:read` | `GET /api/inventory/locations` |
| `inventory:read` | `POST /api/inventory/check-availability` |
| `inventory:read` | `GET /api/admin/catalog/parts` |

## Purchasing

| Scope | Route |
| --- | --- |
| `purchasing:read` | `GET /api/admin/purchasing/requirements` |
| `purchasing:read` | `GET /api/admin/purchasing/so-po-links` |
| `purchasing:read` | `GET /api/admin/purchasing/draft-pos` |
| `purchasing:read` | `GET /api/admin/purchasing/draft-pos/validate` |
| `purchasing:read` | `GET /api/admin/purchasing/draft-pos/PO-000962/validate` |
| `purchasing:read` | `GET /api/admin/purchasing/draft-pos/PO-000962/pdf` |
| `purchasing:read` | `GET /api/admin/purchasing/so-complete-po/preview` |
| `purchasing:draft_po_lines` | `GET /api/admin/purchasing/draft-pos/PO-000962/lines` |
| `purchasing:draft_po_lines` | `PATCH /api/admin/purchasing/draft-pos/PO-000962/lines/10` |
| `purchasing:draft_po_lines` | `DELETE /api/admin/purchasing/draft-pos/PO-000962/lines/10` |
| `purchasing:draft_po_lines` | `POST /api/admin/purchasing/draft-pos/PO-000962/lines` |
| `purchasing:draft_po_lines` | `POST /api/admin/purchasing/draft-pos/PO-000962/lines/reorder` |
| `purchasing:draft_po_lines` | `POST /api/admin/purchasing/draft-pos/PO-000962/lines/normalize-order` |
| `purchasing:draft_po_lines` | `POST /api/admin/purchasing/draft-pos/requested-receipt/backfill` |
| `purchasing:draft_po_lines` | `POST /api/admin/purchasing/draft-pos/PO-000962/requested-receipt` |
| `purchasing:generate_po` | `POST /api/admin/purchasing/generate-po` |
| `purchasing:review_draft` | `POST /api/admin/purchasing/draft-pos/PO-000962/review-draft` |

`POST /api/admin/purchasing/generate-po` is allowed only when the body sets `send_email` to false (or `create_review_draft` to false). That skips the Outlook draft. Open and Released purchase orders are refused by the receipt-date route.

## Quotes already on the portal

| Scope | Route |
| --- | --- |
| `quotes:read` | `GET /api/quotes/pending-review` |
| `quotes:read` | `GET /api/quotes/stats/summary` |
| `quotes:read` | `GET /api/quotes/1` |
| `quotes:read` | `GET /api/quotes/1/pdf` |
| `quotes:read` | `GET /api/orders/bc/quotes` |
| `quotes:read` | `GET /api/admin/quotes` |
| `quotes:read` | `GET /api/admin/quotes/by-number/SQ-003132/pdf` |
| `quotes:read` | `GET /api/admin/quote-review/snapshots` |
| `quotes:read` | `GET /api/admin/quote-review/reviews` |
| `quotes:read` | `GET /api/admin/quote-review/reviews/1` |

## Vendor acknowledgements

| Scope | Route |
| --- | --- |
| `vendor_acks:run` | `GET /api/admin/vendor-acks` |
| `vendor_acks:run` | `POST /api/admin/vendor-acks/run` |

## Still refused

These stay off the key:

- `POST /api/orders/bc/quotes/QUOTE-ID/convert-to-order`
- `POST /api/quotes/3/approve` and `POST /api/quotes/create-bc-quote`
- `POST /api/door-config/generate-quote`
- `POST /api/orders/1/ship` and `POST /api/orders/1/ship-and-invoice`
- `POST /api/orders/invoices/9/post`
- `POST /api/admin/purchasing/so-complete-po`
- `POST /api/admin/purchasing/send-report`
- `POST /api/email-agent/send`
- `POST /api/admin/customers/sync-bc-customers`
- `PUT /api/settings/pricing-tiers`
- `GET /api/auth/users` and any user-management route
- `POST /api/kpi/recalculate` (admin sign-in only; the saved snapshot is what the key can read)
