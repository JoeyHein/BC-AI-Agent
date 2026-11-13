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

## Incoming

`shop_tv_incoming` defaults to off. Off, the Incoming column is empty and `GET /api/shop-tv/incoming` is 404. On, the column lists open Business Central purchase orders by requested receipt date, today and the next 7 days. Overdue dates are red. Each row shows the vendor, our PO number, the supplier order number, carrier and tracking when a shipping email supplied them, the ETA, and the linked sales order numbers and customer names.

The purchase order is read with GET only. The portal does not POST, PATCH, or DELETE a purchase order.

A sales order is linked from, in order: a saved supplier-order map, the PO external document or your reference, line text such as `Built from SO-`, the order tracker `linked_po_number`, or `TAG:SO-` on the email. The customer name comes from that open sales order or the tracker. If none of those name a sales order, the row still shows the PO and the customer is blank.

The TV reads left to right: Incoming, Production, then Pickups stacked above Deliveries.

`incoming_email_matching` defaults to off. Off, the mail poll does not call Microsoft Graph. On, it reads the same mailboxes as vendor-ack intake (`joey@opendc.ca` and `Finance@opendc.ca` unless `VENDOR_ACK_INTAKE_MAILBOXES` is set) with the existing Graph inbox read. The sender domain has to be Upwardor, Elton, DEK, or Global Overhead Doors. TEAMS Transport and Manitoulin are carriers, not vendors. A carrier email applies only when it names exactly one open PO. An unknown sender stays in review until a person types that PO number. Accept and Fix then look up that number across every open purchase order and take the vendor from the PO. A missing or repeated number stays in review. A person's name in the message is not a supplier. The supplier order number has to equal that vendor's order number exactly, and only one open purchase order may match. A saved map is used only when its supplier key matches the sender. An unknown sender that names a PO stays in Settings → Shop TV until accept, fix, or reject. The same Graph message is not reviewed twice.

## Outlook

`OutlookShippingCalendarSource` is the seam for shipping@opendc.ca via Microsoft Graph. It is not connected. Calling it returns no events, so the board does not invent calendar rows.
