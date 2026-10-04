"""Read-only order status, shipment, and pickup/delivery for external keys.

ED-008. Elevated Doors (and any other API-key tenant) can read the Business
Central sales orders that belong to the customer number bound to their key.
Nothing here writes to BC.

Ownership is the key's supplier_account_code compared to the document's
customerNumber. A miss is NOT_FOUND — the same answer as an unknown order —
so a caller cannot tell whether another customer's order exists.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

# Document numbers we will interpolate into an OData $filter. Quotes,
# slashes, and spaces never reach BC.
_ORDER_NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,30}$")

_TRACKING_KEYS = (
    "packageTrackingNo",
    "packageTrackingNumber",
    "trackingNumber",
    "trackingNo",
)
_CARRIER_KEYS = (
    "shippingAgentCode",
    "carrier",
    "carrierCode",
    "shippingAgentServiceCode",
)

# BC status values that mean the sales order itself has been confirmed
# (Draft is the only unconfirmed header status on api/v2.0).
_CONFIRMED_ORDER_STATUSES = {
    "open",
    "released",
    "pending approval",
    "pending prepayment",
}

_PICKUP_METHOD_CODES = {
    "pickup",
    "pick-up",
    "pick up",
    "pu",
    "cpu",
    "willcall",
    "will-call",
    "will call",
    "collect",
}
_DELIVERY_METHOD_CODES = {
    "delivery",
    "deliv",
    "del",
    "dlv",
}


@dataclass
class OrderReadError:
    code: str
    message: str
    retryable: bool


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().casefold()


def _owns(document: Dict[str, Any], account_code: str) -> bool:
    code = _norm(account_code)
    return bool(code) and _norm(document.get("customerNumber")) == code


def _picking_row_owned(row: Dict[str, Any], account_code: str) -> bool:
    """Picking rows use customerNo. A blank customer still belongs to the
    sales order we already authorized — SO numbers are unique."""
    raw = row.get("customerNo") if row.get("customerNo") is not None else row.get("customerNumber")
    if not str(raw or "").strip():
        return True
    return _norm(str(raw)) == _norm(account_code)


def _is_guid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def validate_order_ref(order_ref: str) -> Optional[OrderReadError]:
    """Reject path values we will not send to Business Central."""
    if not order_ref or len(order_ref) > 40:
        return OrderReadError(
            "INVALID_REQUEST",
            "order number is required and must be ≤40 characters",
            False,
        )
    if _is_guid(order_ref):
        return None
    if not _ORDER_NUMBER_RE.fullmatch(order_ref):
        return OrderReadError(
            "INVALID_REQUEST",
            "order number must be an SO document number or a Business Central GUID",
            False,
        )
    return None


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ship_to(document: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    keys = (
        "shipToName",
        "shipToContact",
        "shipToAddressLine1",
        "shipToAddressLine2",
        "shipToCity",
        "shipToState",
        "shipToPostCode",
        "shipToCountry",
    )
    if not any(document.get(key) for key in keys):
        return None
    return {
        "name": document.get("shipToName"),
        "contact": document.get("shipToContact"),
        "addressLine1": document.get("shipToAddressLine1"),
        "addressLine2": document.get("shipToAddressLine2"),
        "city": document.get("shipToCity"),
        "state": document.get("shipToState"),
        "postCode": document.get("shipToPostCode"),
        "country": document.get("shipToCountry"),
    }


def _first_present(document: Dict[str, Any], keys: tuple) -> Optional[str]:
    for key in keys:
        value = document.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _line_views(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    views = []
    for line in lines:
        quantity = _number(line.get("quantity"))
        shipped = _number(line.get("shippedQuantity"))
        outstanding = None
        if quantity is not None and shipped is not None:
            outstanding = quantity - shipped
        sequence = line.get("sequence")
        if sequence is not None:
            try:
                sequence = int(sequence)
            except (TypeError, ValueError):
                sequence = None
        views.append({
            "sequence": sequence,
            "lineType": line.get("lineType"),
            "itemNo": line.get("lineObjectNumber") or None,
            "description": line.get("description"),
            "quantity": quantity,
            "shippedQuantity": shipped,
            "outstandingQuantity": outstanding,
            "unitOfMeasureCode": line.get("unitOfMeasureCode"),
        })
    return views


def fulfillment_status(
    lines: List[Dict[str, Any]],
    *,
    fully_shipped_flag: bool,
    posted_only: bool,
    shipment_count: int,
) -> str:
    """not_shipped | partially_shipped | fully_shipped.

    Item lines drive the answer. Comment lines (the pickup banner, freight
    notes) are ignored. A posted order that no longer exists as an open
    sales order is fully_shipped: BC has already moved it to posted shipments.
    """
    if posted_only:
        return "fully_shipped"

    item_lines = [
        line for line in lines
        if (line.get("lineType") or "Item") == "Item" and line.get("itemNo")
    ]
    if not item_lines:
        if fully_shipped_flag or shipment_count:
            return "fully_shipped"
        return "not_shipped"

    quantities = [line.get("quantity") for line in item_lines]
    shipped = [line.get("shippedQuantity") for line in item_lines]
    if any(value is None for value in quantities) or any(value is None for value in shipped):
        if fully_shipped_flag:
            return "fully_shipped"
        if shipment_count:
            return "partially_shipped"
        return "not_shipped"

    total_qty = sum(quantities)
    total_shipped = sum(max(0.0, value) for value in shipped)
    if fully_shipped_flag or (total_qty > 0 and total_shipped >= total_qty):
        return "fully_shipped"
    if total_shipped > 0 or shipment_count:
        return "partially_shipped"
    return "not_shipped"


def _comment_says_pickup(lines: List[Dict[str, Any]]) -> bool:
    """The configurator writes a Comment line for customer pickup.

    Item descriptions such as "CENTER PICKUP KIT" are hardware, not a
    fulfillment method, so only Comment lines count.
    """
    for line in lines:
        if (line.get("lineType") or "") != "Comment":
            continue
        text = (line.get("description") or "").upper()
        if "CUSTOMER PICKUP" in text or text.startswith("** PICKUP"):
            return True
        if "THIS ORDER" in text and "PICKUP" in text:
            return True
    return False


def _classify_method_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip().casefold()
    if not text or "center" in text:
        return None
    if text in _PICKUP_METHOD_CODES or "pickup" in text or "pick-up" in text or "pick up" in text:
        return "pickup"
    if text in _DELIVERY_METHOD_CODES or "deliv" in text:
        return "delivery"
    return None


def delivery_method(
    lines: List[Dict[str, Any]],
    shipment_method_code: Optional[str],
    load_method: Optional[str],
) -> Dict[str, Optional[str]]:
    """pickup | delivery | unknown, plus which BC field decided it."""
    if _comment_says_pickup(lines):
        return {"method": "pickup", "methodSource": "order_comment"}
    from_code = _classify_method_text(shipment_method_code)
    if from_code:
        return {"method": from_code, "methodSource": "shipment_method"}
    from_load = _classify_method_text(load_method)
    if from_load:
        return {"method": from_load, "methodSource": "load_method"}
    return {"method": "unknown", "methodSource": None}


def confirmation_state(
    *,
    order_status: Optional[str],
    scheduled_date: Optional[str],
    fulfillment: str,
    method: str,
) -> Dict[str, Any]:
    """Scheduling (requested delivery date) and whether it is confirmed.

    confirmation:
      unscheduled | scheduled | confirmed | partially_fulfilled
      | picked_up | delivered | fulfilled
    confirmed is false only while nothing has been accepted or shipped.
    """
    if fulfillment == "fully_shipped":
        if method == "pickup":
            name = "picked_up"
        elif method == "delivery":
            name = "delivered"
        else:
            name = "fulfilled"
        return {"confirmed": True, "confirmation": name}
    if fulfillment == "partially_shipped":
        return {"confirmed": True, "confirmation": "partially_fulfilled"}

    status = (order_status or "").strip().casefold()
    if status in _CONFIRMED_ORDER_STATUSES:
        return {"confirmed": True, "confirmation": "confirmed"}
    if scheduled_date:
        return {"confirmed": False, "confirmation": "scheduled"}
    return {"confirmed": False, "confirmation": "unscheduled"}


def _shipment_view(shipment: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "shipmentId": shipment.get("id"),
        "shipmentNumber": shipment.get("number"),
        "orderNumber": shipment.get("orderNumber"),
        "externalDocumentNumber": shipment.get("externalDocumentNumber") or None,
        "shipmentDate": shipment.get("shipmentDate"),
        "postingDate": shipment.get("postingDate"),
        "trackingNumber": _first_present(shipment, _TRACKING_KEYS),
        "carrier": _first_present(shipment, _CARRIER_KEYS),
        "shipToName": shipment.get("shipToName"),
        "shipTo": _ship_to(shipment),
    }


def _earliest_date(values: List[Optional[str]]) -> Optional[str]:
    present = sorted(value for value in values if value)
    return present[0] if present else None


def _picking_view(
    queue_rows: List[Dict[str, Any]],
    posted_rows: List[Dict[str, Any]],
    *,
    available: bool,
) -> Dict[str, Any]:
    queue = queue_rows[0] if queue_rows else {}
    posted = posted_rows[0] if posted_rows else {}
    return {
        "available": available,
        "queueStatus": queue.get("status"),
        "pickingDate": queue.get("pickingDate"),
        "shipmentDate": queue.get("shipmentDate") or posted.get("postingDate"),
        "loadMethod": queue.get("loadMethod") or posted.get("loadMethod"),
        "posted": bool(posted_rows),
        "shipmentNo": posted.get("shipmentNo") or queue.get("shipmentNo"),
    }


def build_order_view(
    order: Dict[str, Any],
    shipments: List[Dict[str, Any]],
    picking: Dict[str, Any],
    *,
    posted_only: bool,
) -> Dict[str, Any]:
    """Shape one order for the external API. `order` is a BC sales order
    or a header reconstructed from posted shipments."""
    raw_lines = order.get("salesOrderLines") or order.get("lines") or []
    lines = _line_views(raw_lines)
    shipment_views = [_shipment_view(row) for row in shipments]
    fully_shipped_flag = bool(order.get("fullyShipped"))
    status_name = fulfillment_status(
        lines,
        fully_shipped_flag=fully_shipped_flag,
        posted_only=posted_only,
        shipment_count=len(shipment_views),
    )
    load_method = picking.get("loadMethod")
    method = delivery_method(lines, order.get("shipmentMethodCode"), load_method)
    scheduled = order.get("requestedDeliveryDate") or None
    shipment_date = _earliest_date(
        [row.get("shipmentDate") for row in shipment_views]
    ) or picking.get("shipmentDate")
    confirmation = confirmation_state(
        order_status=order.get("status"),
        scheduled_date=scheduled,
        fulfillment=status_name,
        method=method["method"],
    )
    ship_to = _ship_to(order) or (shipment_views[0]["shipTo"] if shipment_views else None)
    fulfillment = {
        "orderNumber": order.get("number"),
        "customerNumber": order.get("customerNumber"),
        "method": method["method"],
        "methodSource": method["methodSource"],
        "scheduledDate": scheduled,
        "shipmentDate": shipment_date,
        "confirmed": confirmation["confirmed"],
        "confirmation": confirmation["confirmation"],
        "fulfillmentStatus": status_name,
        "shipTo": ship_to,
        "picking": picking,
    }
    return {
        "orderNumber": order.get("number"),
        "orderId": order.get("id"),
        "customerNumber": order.get("customerNumber"),
        "customerName": order.get("customerName"),
        "externalDocumentNumber": order.get("externalDocumentNumber") or None,
        "status": order.get("status"),
        "source": "posted_shipment" if posted_only else "open_order",
        "orderDate": order.get("orderDate"),
        "requestedDeliveryDate": scheduled,
        "currency": order.get("currencyCode") or None,
        "totalAmountExcludingTax": _number(order.get("totalAmountExcludingTax")),
        "totalTaxAmount": _number(order.get("totalTaxAmount")),
        "totalAmountIncludingTax": _number(order.get("totalAmountIncludingTax")),
        "fullyShipped": fully_shipped_flag or posted_only,
        "outstandingKnown": not posted_only,
        "fulfillmentStatus": status_name,
        "shipmentMethodCode": order.get("shipmentMethodCode") or None,
        "shipTo": ship_to,
        "lines": lines,
        "shipments": shipment_views,
        "fulfillment": fulfillment,
    }


def summary_view(order: Dict[str, Any]) -> Dict[str, Any]:
    method = delivery_method([], order.get("shipmentMethodCode"), None)
    return {
        "orderNumber": order.get("number"),
        "orderId": order.get("id"),
        "externalDocumentNumber": order.get("externalDocumentNumber") or None,
        "customerNumber": order.get("customerNumber"),
        "customerName": order.get("customerName"),
        "status": order.get("status"),
        "orderDate": order.get("orderDate"),
        "requestedDeliveryDate": order.get("requestedDeliveryDate") or None,
        "currency": order.get("currencyCode") or None,
        "totalAmountIncludingTax": _number(order.get("totalAmountIncludingTax")),
        "fullyShipped": bool(order.get("fullyShipped")),
        "shipmentMethodCode": order.get("shipmentMethodCode") or None,
        "method": method["method"],
    }


def _order_from_shipments(
    shipments: List[Dict[str, Any]], account_code: str
) -> Dict[str, Any]:
    first = shipments[0]
    return {
        "id": None,
        "number": first.get("orderNumber"),
        "customerNumber": first.get("customerNumber") or account_code,
        "customerName": first.get("customerName"),
        "externalDocumentNumber": first.get("externalDocumentNumber"),
        "status": "Posted",
        "orderDate": None,
        "requestedDeliveryDate": None,
        "currencyCode": first.get("currencyCode"),
        "fullyShipped": True,
        "shipmentMethodCode": None,
        "salesOrderLines": [],
        "shipToName": first.get("shipToName"),
        "shipToContact": first.get("shipToContact"),
        "shipToAddressLine1": first.get("shipToAddressLine1"),
        "shipToAddressLine2": first.get("shipToAddressLine2"),
        "shipToCity": first.get("shipToCity"),
        "shipToState": first.get("shipToState"),
        "shipToPostCode": first.get("shipToPostCode"),
        "shipToCountry": first.get("shipToCountry"),
    }


def _not_found() -> OrderReadError:
    return OrderReadError("NOT_FOUND", "Order not found", False)


def _upstream(exc: Exception) -> OrderReadError:
    logger.warning("BC order read failed: %s", exc)
    return OrderReadError(
        "UPSTREAM_ERROR",
        "Business Central order read failed",
        True,
    )


def _http_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    return response is not None and getattr(response, "status_code", None) == 404


def _load_picking(order_number: Optional[str], account_code: str) -> Dict[str, Any]:
    """Best-effort. A missing picking extension must not fail the order read."""
    if not order_number:
        return _picking_view([], [], available=False)
    try:
        queue = [
            row for row in (bc_client.get_picking_queue() or [])
            if (row.get("salesOrderNo") or "") == order_number
            and _picking_row_owned(row, account_code)
        ]
        posted = bc_client.get_posted_picking_headers(sales_order_no=order_number) or []
        posted = [row for row in posted if _picking_row_owned(row, account_code)]
        available = True
        if not queue and not posted:
            available = bool(bc_client.picking_api_available())
        return _picking_view(queue, posted, available=available)
    except Exception as exc:
        logger.warning("Picking read failed for %s: %s", order_number, exc)
        return _picking_view([], [], available=False)


def _shipment_visible(row: Dict[str, Any], account_code: str, *, allow_blank: bool) -> bool:
    """A shipment with no customerNumber is visible only when the open
    sales order was already authorized. Posted-only lookups must carry
    customerNumber, or a blank row would leak another customer's freight.
    """
    if not str(row.get("customerNumber") or "").strip():
        return allow_blank
    return _owns(row, account_code)


def _owned_shipments(
    order_number: str, account_code: str, *, allow_blank: bool
) -> List[Dict[str, Any]] | OrderReadError:
    try:
        shipments = bc_client.get_sales_shipments_by_order_number(order_number) or []
    except Exception as exc:
        return _upstream(exc)
    if shipments and not all(
        _shipment_visible(row, account_code, allow_blank=allow_blank) for row in shipments
    ):
        return _not_found()
    return shipments


def read_order(account_code: str, order_ref: str) -> Dict[str, Any] | OrderReadError:
    """F1 + F2 for one sales order that belongs to this customer."""
    invalid = validate_order_ref(order_ref)
    if invalid:
        return invalid

    posted_only = False
    order: Optional[Dict[str, Any]] = None
    try:
        if _is_guid(order_ref):
            try:
                order = bc_client.get_sales_order(order_ref)
            except requests.HTTPError as exc:
                if not _http_not_found(exc):
                    return _upstream(exc)
                order = None
            if order is not None:
                order["salesOrderLines"] = bc_client.get_order_lines(order_ref) or []
        else:
            order = bc_client.get_sales_order_with_lines_by_number(order_ref)
    except Exception as exc:
        return _upstream(exc)

    if order is not None and not _owns(order, account_code):
        return _not_found()

    order_number = (order or {}).get("number") or (None if _is_guid(order_ref) else order_ref)
    shipments: List[Dict[str, Any]] = []
    if order_number:
        loaded = _owned_shipments(
            order_number, account_code, allow_blank=order is not None,
        )
        if isinstance(loaded, OrderReadError):
            # Foreign shipment on an order we already proved we own is an
            # upstream data oddity — still hide it. A not-found here only
            # applies when we have no open order to anchor ownership.
            if order is None:
                return loaded if loaded.code == "NOT_FOUND" else loaded
            if loaded.code != "NOT_FOUND":
                return loaded
            shipments = []
        else:
            shipments = loaded

    if order is None:
        if not shipments:
            return _not_found()
        order = _order_from_shipments(shipments, account_code)
        posted_only = True
        order_number = order.get("number")

    picking = _load_picking(order_number, account_code)
    return build_order_view(order, shipments, picking, posted_only=posted_only)


def list_orders(account_code: str) -> Dict[str, Any] | OrderReadError:
    """Open sales orders for the customer bound to the API key."""
    if not (account_code or "").strip():
        return OrderReadError("INVALID_REQUEST", "supplier account code is required", False)
    try:
        page = bc_client.get_sales_orders_by_customer_number(account_code)
    except Exception as exc:
        return _upstream(exc)
    rows = page.get("value") or []
    owned = [row for row in rows if _owns(row, account_code)]
    owned.sort(key=lambda row: (row.get("orderDate") or "", row.get("number") or ""), reverse=True)
    return {
        "customerNumber": account_code,
        "complete": bool(page.get("complete", True)),
        "orders": [summary_view(row) for row in owned],
    }
