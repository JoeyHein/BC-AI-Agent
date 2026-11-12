# Shop TV board

Staff cast `/shop-tv` to a shop TV from a Chrome tab. The board is off until an admin turns on `shop_tv_board` in Settings. Off, `GET /api/shop-tv/board` and `GET /api/shop-tv/enabled` are 404 and the nav link is hidden.

Shop time is America/Regina. The screen shows today and the next 7 days. It refreshes every 60 seconds. A cast URL uses a kiosk token, not a staff login.

## Auth

A staff JWT on a TV is the wrong secret. That login can change quotes, orders, and settings, and a cast tab is easy to see. The kiosk token is a separate secret:

- Shown once, stored as a SHA-256 hash
- Scope is only `shop_tv:read`
- Accepted by the board read (`?kiosk=` or `X-Shop-Tv-Token`)
- Revoked from Settings → Shop TV. The next refresh is rejected
- Cannot open settings or any other route

A staff login with production or sales-order access can still open the board in the portal. No token is 401. A revoked token is 403. The flag off is 404 even when a token is present.

Migration `d1e2f3a4b5c7` adds `shop_tv_kiosk_tokens`. The on/off switch and the lane lists live in `app_settings` (`shop_tv_board`, `shop_tv_board_lanes`) and do not add a table.

## Lane mapping

Anything without a real date stays off the board. `0001-01-01` and the order date are not dates. Midnight means there is no appointment time.

| Lane | Included when | Date |
| --- | --- | --- |
| Production | One open sales order per row. Draft and fully shipped stay off. Business Central production orders are not read. | Portal `sales_orders.scheduled_date` when it is set (Scheduled). Otherwise the sales order shipment date: header `shipmentDate`, else the earliest line `shipmentDate` (Shipment). |
| Pickups | Open, not fully shipped, shipment method or listed shipping agent is a pickup code | Shipment date (header, else earliest line), then promised delivery date, then requested delivery date |
| Deliveries | Open, not fully shipped, shipment method or listed shipping agent is a delivery code | Same dates as pickups. Destination is the ship-to address |

Default pickup codes: `PICKUP`, `PICK UP`, `PICK-UP`, `PU`, `WILL CALL`, `COLLECT`, `CUSTOMER PICKUP`.

Default delivery codes: `DELIVERY`, `TRUCK`, `FREIGHT`, `OUR TRUCK`, `COURIER`.

A shipping agent does nothing until its code is listed, or Settings says any other agent is a delivery. That switch defaults off. `shipmentMethodId` is a GUID on the standard sales order and does not choose a lane. This portal already reads `shipmentMethodCode` when Business Central sends it.

The production date is the portal scheduled date because that column is already the production/picking date stored on the sales order (`sales_orders.scheduled_date`, migration `h2i3j4k5l6m7`). When it is blank, the shipment date on the same sales order is the build date. Promised and requested dates are customer dates and stay on Pickups and Deliveries. The order date is never used. A sales order with neither a scheduled date nor a shipment date stays off Production. The row summary is the item descriptions on that sales order, with comment lines skipped.

An order can be in Production and in Pickups or Deliveries. It is never in both Pickups and Deliveries.

Earlier than today is overdue (red). A clock time already passed today is late (red). Later than today plus 7 days stays off.

## Outlook

`OutlookShippingCalendarSource` is the seam for shipping@opendc.ca via Microsoft Graph. It is not connected. Calling it returns no events, so the board does not invent calendar rows.
