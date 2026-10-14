# Staff KPI dashboard

The staff home page is a read-only scorecard. Every figure is calculated from Business Central. Two dates that Business Central does not store are filled in from the portal when the portal already has them: the time a purchase order email was sent, and the time an Upwardor acknowledgement email arrived.

Nothing on this page creates, edits, posts, ships, or emails a Business Central document.

The same numbers are available to the assistant with a staff service key:

- `GET /api/kpi/dashboard?from=YYYY-MM-DD&to=YYYY-MM-DD`
- `GET /api/kpi/dashboard/purchasing`
- `GET /api/kpi/dashboard/sales`
- `GET /api/kpi/dashboard/financial`
- `GET /api/kpi/dashboard/operations`

The key needs all four read scopes: `orders:read`, `purchasing:read`, `quotes:read`, and `inventory:read`. Results are cached for 10 minutes. `refresh=true` skips the cache.

Green means on track, amber means have a look, red means it needs attention. A row in the sales-order to purchase-order list is red when it took more than 5 days, or when the purchase order still has not been sent after 5 days.

## What each number means

### Purchasing and vendors

1. **SO to PO sent.** Average days from the sales order date to the day the purchase order was sent to the vendor, plus every pair. The sent date is the portal's email-sent time when that was recorded. Otherwise it is the purchase order date in Business Central, and only after the order is open. A draft has not been sent.

2. **PO sent to vendor acknowledgement.** Average days by vendor from the sent date to the acknowledgement. Acknowledgement dates come from the portal's Upwardor inbox. A promised receipt date in Business Central is a delivery promise, not an acknowledgement, so it is not used.

3. **Unacknowledged POs.** Purchase orders that have been sent, are not fully received, and have no Upwardor acknowledgement on file, with age in days. This is the open list as of today, so an old one stays visible even if it falls outside the date range.

4. **Vendor on-time rate.** Share of purchase orders whose first receipt in the date range was on or before the required receipt date, by vendor.

### Sales

5. **Weekly and monthly sales.** Posted sales invoices, before tax. Compared with the previous period and with the same dates last year.

6. **Product mix.** Sales split into commercial, residential, and aluminum, with the items that moved the most in each. TX450 and Thermalex are commercial. Kanata, Craft, and anything marked residential are residential. AL976 and aluminum are aluminum. The default file also treats TX380, TX500, and TX760 as commercial, and SWD, Panorama, and Solalite as aluminum, because those are the other series in the catalog. Lines that match nothing are Other.

7. **Operator sales by brand.** Invoice lines that name LiftMaster, Micanan or McKinnon, or Guardian.

8. **Quote conversion and open quote value.** Conversion is orders in the date range whose external document number is a quote that is no longer open, divided by those orders plus quotes still open from the same dates. Open quote value is every quote still sitting in Business Central, before tax.

### Financial

9. **Gross margin.** Invoice line amount before tax, minus quantity times the unit cost on the item card, by order and by product line. Orders under 20% are flagged. The cutoff is in the product-line file.

10. **Purchase invoice vs PO.** Posted purchase invoice total minus the purchase order total, before tax, by vendor.

11. **AR aging, total, and deposits.** The total is the balance on customer cards. The buckets are open sales invoices by due date. Deposits are open customer payments when Business Central returns that list.

12. **Open order backlog.** Open sales orders, the part not yet shipped, before tax.

### Operations

13. **Order to ship.** Days from the sales order date to the shipment date.

14. **Inventory.** On-hand quantity times unit cost, items with stock and no sale in the window, and items below reorder point when that field is available.

15. **Freight as a percent of sales.** Invoice lines that match the freight words in the product-line file, divided by sales before tax.

## Where Business Central is missing or partial

These limits are also listed on the dashboard under Data notes.

| KPI | What is missing |
| --- | --- |
| SO to PO sent | Fully shipped sales orders and fully received purchase orders leave Business Central's open lists. Older pairs are missing unless the portal still links them. Many purchase orders have no email-sent time, so the purchase order date is used instead. |
| PO to acknowledgement | Business Central has no vendor acknowledgement date. Only Upwardor acknowledgements stored by the portal are included. Other vendors have no acknowledgement time. |
| Unacknowledged POs | A vendor who confirms outside the Upwardor inbox still shows as unacknowledged. |
| Vendor on-time | The required date stays on the purchase order only while that order is still open. Older, fully posted orders are left out. |
| Product mix | Lines that do not match the series list are Other. The list can miss a new series until the file is updated. |
| Operator sales | Only lines that name the brand are counted. |
| Quote conversion | Converted quotes usually disappear from Business Central, and fully shipped orders disappear too. An order counts only when its external document number is the quote number. |
| Gross margin | Cost is the item card unit cost, not the posted cost of goods. Lines with no cost are incomplete. |
| Purchase invoice vs PO | The purchase order total is available only while the order is still open. Closed orders are counted without a difference. |
| AR aging and deposits | Open invoices are aged at the full amount, because the invoice list does not say what is still unpaid. The buckets may not match the customer-card total. Deposits are blank unless Business Central returns open customer payments. Credit balances on customer cards are not deposits. |
| Order to ship | The shipment often has no original order date. The date is taken from the sales order only while that order is still open. |
| Inventory reorder | Reorder point is not on the standard item list. It appears only when the Items web service includes Reorder Point. |
| Freight | Freight posted to an account whose description does not match the freight words is not included. |

Weekly and monthly sales, and open order backlog, use fields Business Central does publish (posted invoice totals, and quantity still to ship on open orders).

## Changing the product lines

Edit `backend/app/services/kpi_product_lines.json`, or set `KPI_PRODUCT_LINE_MAP_FILE` to another JSON file, or set `KPI_PRODUCT_LINE_MAP` to the JSON itself. A token matches on a word boundary, so TX450 matches TX450-0907 and does not match TX4500. The first matching product line wins. Put a specific series ahead of a general word like aluminum.
