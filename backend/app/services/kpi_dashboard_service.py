"""Read-only KPI dashboard.

Every Business Central call in this module is a GET. Portal rows are read
for two dates Business Central does not store: the purchase-order email
time (``POAgentLog.emailed_at``) and Upwardor acknowledgement time
(``vendor_order_acks.received_at``). Results are cached per date range.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any, Optional

import requests
from sqlalchemy.orm import Session

from app.integrations.bc.client import bc_client
from app.services.kpi_compute import build_kpi_dashboard, parse_date, shift_year
from app.services.kpi_product_map import load_product_map

logger = logging.getLogger(__name__)

CACHE_SECONDS = 600
_MAX_RANGE_DAYS = 800

_DEPOSITS_MISSING = (
    "Customer deposits and prepayments are not on the standard invoice or customer list. "
    "Business Central did not return open customer payments, so deposits are blank. "
    "Credit balances on customer cards are shown separately and are not the same as deposits."
)


class KpiDashboardService:
    def __init__(self):
        self.client = bc_client
        self._cache: dict[tuple, tuple[float, dict]] = {}

    def get_dashboard(
        self,
        db: Optional[Session],
        start: date,
        end: date,
        today: Optional[date] = None,
        refresh: bool = False,
    ) -> dict:
        today = today or date.today()
        product_map = load_product_map()
        key = (start.isoformat(), end.isoformat(), product_map.source, product_map.low_margin_pct)
        now = time.monotonic()
        if not refresh:
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                payload = dict(hit[1])
                payload["cached"] = True
                payload["cache_seconds"] = CACHE_SECONDS
                return payload
        payload = self._build(db, start, end, today, product_map)
        payload["cached"] = False
        payload["cache_seconds"] = CACHE_SECONDS
        self._cache[key] = (now + CACHE_SECONDS, payload)
        return dict(payload)

    def _build(self, db, start: date, end: date, today: date, product_map) -> dict:
        errors: dict[str, str] = {}
        window_start = _fetch_start(start, end, today, product_map.slow_mover_days)
        invoices = self._try("sales_invoices", lambda: self._invoices(window_start, end), errors, [])
        bundle = {
            "sales_orders": self._try("sales_orders", self._sales_orders, errors, []),
            "purchase_orders": self._try("purchase_orders", self._purchase_orders, errors, []),
            "receipts": self._try("purchase_receipts", lambda: self._receipts(start, end), errors, []),
            "invoices": invoices,
            "open_invoices": self._try("open_invoices", self._open_invoices, errors, []),
            "quotes": self._try("sales_quotes", self._quotes, errors, []),
            "shipments": self._try("sales_shipments", lambda: self._shipments(start, end), errors, []),
            "items": self._try("items", self._items, errors, []),
            "customers": self._try("customers", self._customers, errors, []),
            "purchase_invoices": self._try(
                "purchase_invoices", lambda: self._purchase_invoices(start, end), errors, [],
            ),
            "deposits": self._deposits(),
            "reorder_state": "missing",
            "slow_window_start": min(window_start, today - timedelta(days=product_map.slow_mover_days)).isoformat(),
            "errors": errors,
        }
        self._attach_reorder(bundle)
        sends, acks = self._portal(db, errors)
        bundle["po_sends"] = sends
        bundle["acks"] = acks
        logger.info("KPI dashboard computed for %s to %s", start.isoformat(), end.isoformat())
        return build_kpi_dashboard(bundle, start, end, today, product_map)

    def _try(self, name: str, fn, errors: dict, default):
        try:
            return fn()
        except Exception as exc:
            logger.warning("KPI source %s failed: %s", name, exc.__class__.__name__)
            errors[name] = f"Business Central did not return {name.replace('_', ' ')}."
            return default

    def _company(self) -> str:
        company_id = self.client.company_id
        if not company_id:
            raise RuntimeError("Business Central company is not configured")
        return company_id

    def _get_all(self, relative: str) -> list[dict]:
        """Follow next-page links. GET only. Raises on an HTTP error."""
        url = f"{self.client.base_url}/companies({self._company()})/{relative}"
        rows: list[dict] = []
        while url:
            token = self.client._get_access_token()
            if not token:
                raise RuntimeError("Business Central is not signed in")
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=90,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Business Central returned {response.status_code}")
            payload = response.json()
            rows.extend(payload.get("value") or [])
            url = payload.get("@odata.nextLink")
        return rows

    def _sales_orders(self) -> list[dict]:
        rows = self._get_all("salesOrders?$expand=salesOrderLines")
        return [_order(row) for row in rows]

    def _purchase_orders(self) -> list[dict]:
        rows = self._get_all("purchaseOrders?$expand=purchaseOrderLines")
        return [_purchase_order(row) for row in rows]

    def _invoices(self, start: date, end: date) -> list[dict]:
        relative = (
            "salesInvoices?$expand=salesInvoiceLines"
            f"&$filter=postingDate ge {start.isoformat()} and postingDate le {end.isoformat()}"
        )
        return [_sales_invoice(row) for row in self._get_all(relative)]

    def _open_invoices(self) -> list[dict]:
        relative = (
            "salesInvoices?$filter=status eq 'Open'"
            "&$select=number,dueDate,postingDate,status,totalAmountExcludingTax,customerNumber,customerName"
        )
        return [_open_invoice(row) for row in self._get_all(relative)]

    def _quotes(self) -> list[dict]:
        relative = (
            "salesQuotes?$select=number,documentDate,customerName,customerNumber,"
            "totalAmountExcludingTax,externalDocumentNumber,status"
        )
        return [_quote(row) for row in self._get_all(relative)]

    def _shipments(self, start: date, end: date) -> list[dict]:
        window = f"postingDate ge {start.isoformat()} and postingDate le {end.isoformat()}"
        try:
            rows = self._get_all(
                "salesShipments?$filter=" + window + "&$select=number,orderNumber,postingDate,orderDate"
            )
        except Exception:
            rows = self._get_all(
                "salesShipments?$filter=" + window + "&$select=number,orderNumber,postingDate"
            )
        return [_shipment(row) for row in rows]

    def _receipts(self, start: date, end: date) -> list[dict]:
        relative = (
            "purchaseReceipts?$filter="
            f"postingDate ge {start.isoformat()} and postingDate le {end.isoformat()}"
            "&$select=number,orderNumber,postingDate,vendorNumber,vendorName"
        )
        return [_receipt(row) for row in self._get_all(relative)]

    def _purchase_invoices(self, start: date, end: date) -> list[dict]:
        relative = (
            "purchaseInvoices?$filter="
            f"postingDate ge {start.isoformat()} and postingDate le {end.isoformat()}"
            " and (status eq 'Open' or status eq 'Paid')"
            "&$select=number,orderNumber,postingDate,vendorNumber,vendorName,totalAmountExcludingTax,status"
        )
        return [_purchase_invoice(row) for row in self._get_all(relative)]

    def _items(self) -> list[dict]:
        """Item cards. The items endpoint does not send a next-page link, so page with $skip."""
        company = self._company()
        token = self.client._get_access_token()
        if not token:
            raise RuntimeError("Business Central is not signed in")
        rows: list[dict] = []
        skip = 0
        page_size = 1000
        while True:
            response = requests.get(
                f"{self.client.base_url}/companies({company})/items"
                f"?$top={page_size}&$skip={skip}"
                "&$select=number,displayName,inventory,unitCost,itemCategoryCode",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=90,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Business Central returned {response.status_code}")
            chunk = response.json().get("value") or []
            rows.extend(chunk)
            if len(chunk) < page_size:
                break
            skip += page_size
        return [_item(row) for row in rows]

    def _customers(self) -> list[dict]:
        try:
            rows = self._get_all("customers?$select=number,displayName,balanceDue&$filter=balanceDue ne 0")
        except Exception:
            rows = self._get_all("customers?$select=number,displayName,balanceDue")
        return [_customer(row) for row in rows if _num(row.get("balanceDue"))]

    def _attach_reorder(self, bundle: dict) -> None:
        try:
            from app.services.bc_production_service import bc_production_service

            rows = bc_production_service._make_odata_request_all(
                "Items", query_params={"$select": "No,Reorder_Point"},
            )
        except Exception as exc:
            logger.warning("KPI reorder points unavailable: %s", exc.__class__.__name__)
            bundle["reorder_state"] = "missing"
            return
        if not rows or "Reorder_Point" not in (rows[0] or {}):
            bundle["reorder_state"] = "missing"
            return
        points = {
            (row.get("No") or "").upper(): row.get("Reorder_Point")
            for row in rows
            if row.get("No")
        }
        for item in bundle["items"]:
            number = (item.get("number") or "").upper()
            if number in points and points[number] is not None:
                item["reorder_point"] = _num(points[number])
        bundle["reorder_state"] = "ok"

    def _deposits(self) -> dict:
        try:
            rows = self._get_all(
                "customerLedgerEntries?$filter=open eq true and documentType eq 'Payment'"
                "&$select=remainingAmount,customerNumber,documentType&$top=2000"
            )
        except Exception:
            return {"state": "missing", "amount": None, "detail": _DEPOSITS_MISSING}
        capped = len(rows) >= 2000
        rows = rows[:2000]
        if not rows:
            return {
                "state": "ok",
                "amount": 0.0,
                "detail": "Open customer payments in Business Central, which are unapplied deposits and prepayments.",
            }
        if "remainingAmount" not in rows[0]:
            return {"state": "missing", "amount": None, "detail": _DEPOSITS_MISSING}
        amount = round(sum(abs(_num(row.get("remainingAmount"))) for row in rows), 2)
        detail = "Open customer payments in Business Central, which are unapplied deposits and prepayments."
        if capped:
            detail += " The list stopped at 2,000 payments, so the total can be short."
            return {"state": "partial", "amount": amount, "detail": detail}
        return {"state": "ok", "amount": amount, "detail": detail}

    def _portal(self, db: Optional[Session], errors: dict) -> tuple[list[dict], list[dict]]:
        if db is None:
            return [], []
        try:
            from app.db.models import POAgentLog, VendorOrderAck

            sends = []
            for row in db.query(POAgentLog).all():
                allocations = row.so_allocations or {}
                if not row.bc_po_number and not allocations and not row.emailed_at:
                    continue
                sends.append({
                    "po_number": row.bc_po_number,
                    "emailed_at": row.emailed_at.isoformat() if row.emailed_at else None,
                    "so_numbers": [str(number) for number in allocations.keys()],
                    "vendor_number": row.vendor_id,
                    "vendor_name": row.vendor_name,
                })
            acks = []
            for row in db.query(VendorOrderAck).all():
                acks.append({
                    "po_number": row.our_po_number,
                    "vendor_number": row.vendor_no,
                    "vendor_name": row.vendor_no,
                    "received_at": row.received_at.isoformat() if row.received_at else None,
                    "status": row.status,
                })
            return sends, acks
        except Exception as exc:
            logger.warning("KPI portal records unavailable: %s", exc.__class__.__name__)
            errors["portal"] = "The portal's purchase-order email log or acknowledgement log could not be read."
            return [], []


def _fetch_start(start: date, end: date, today: date, slow_days: int) -> date:
    length = (end - start).days
    prior_start = (start - timedelta(days=1)) - timedelta(days=length)
    week_start = end - timedelta(days=end.weekday()) - timedelta(days=7)
    month_start = (end.replace(day=1) - timedelta(days=1)).replace(day=1)
    slow_start = today - timedelta(days=slow_days)
    return min(start, prior_start, shift_year(start), shift_year(week_start), shift_year(month_start), week_start, month_start, slow_start)


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _date_text(value: Any) -> Optional[str]:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else None


def _lines(raw_lines: list, kind: str) -> list[dict]:
    out = []
    for line in raw_lines or []:
        if kind == "sales":
            amount = line.get("amountExcludingTax")
            if amount is None:
                amount = line.get("netAmount")
            out.append({
                "line_type": line.get("lineType") or "",
                "item_number": line.get("lineObjectNumber") or "",
                "description": line.get("description") or "",
                "quantity": _num(line.get("quantity")),
                "shipped_quantity": _num(line.get("shippedQuantity")),
                "amount": _num(amount),
            })
        else:
            out.append({
                "line_type": line.get("lineType") or "",
                "item_number": line.get("lineObjectNumber") or "",
                "description": line.get("description") or "",
                "quantity": _num(line.get("quantity")),
                "received_quantity": _num(line.get("receivedQuantity")),
                "expected_receipt_date": _date_text(line.get("expectedReceiptDate")),
            })
    return out


def _order(row: dict) -> dict:
    return {
        "number": row.get("number") or "",
        "order_date": _date_text(row.get("orderDate")),
        "customer_name": row.get("customerName") or "",
        "customer_number": row.get("customerNumber") or "",
        "external_document": row.get("externalDocumentNumber") or "",
        "amount": _num(row.get("totalAmountExcludingTax")),
        "lines": _lines(row.get("salesOrderLines") or [], "sales"),
    }


def _purchase_order(row: dict) -> dict:
    return {
        "number": row.get("number") or "",
        "status": row.get("status") or "",
        "order_date": _date_text(row.get("orderDate")),
        "requested_receipt_date": _date_text(row.get("requestedReceiptDate")),
        "vendor_number": row.get("vendorNumber") or "",
        "vendor_name": row.get("vendorName") or "",
        "amount": _num(row.get("totalAmountExcludingTax")),
        "external_document": row.get("externalDocumentNumber") or "",
        "lines": _lines(row.get("purchaseOrderLines") or [], "purchase"),
    }


def _sales_invoice(row: dict) -> dict:
    lines = []
    for line in row.get("salesInvoiceLines") or []:
        amount = line.get("amountExcludingTax")
        if amount is None:
            amount = line.get("netAmount")
        lines.append({
            "line_type": line.get("lineType") or "",
            "item_number": line.get("lineObjectNumber") or "",
            "description": line.get("description") or "",
            "quantity": _num(line.get("quantity")),
            "amount": _num(amount),
        })
    return {
        "number": row.get("number") or "",
        "posting_date": _date_text(row.get("postingDate")),
        "customer_name": row.get("customerName") or "",
        "customer_number": row.get("customerNumber") or "",
        "amount": _num(row.get("totalAmountExcludingTax")),
        "status": row.get("status") or "",
        "order_number": row.get("orderNumber") or "",
        "lines": lines,
    }


def _open_invoice(row: dict) -> dict:
    return {
        "number": row.get("number") or "",
        "due_date": _date_text(row.get("dueDate")),
        "posting_date": _date_text(row.get("postingDate")),
        "status": row.get("status") or "",
        "amount": _num(row.get("totalAmountExcludingTax")),
        "customer_name": row.get("customerName") or "",
        "customer_number": row.get("customerNumber") or "",
    }


def _quote(row: dict) -> dict:
    return {
        "number": row.get("number") or "",
        "document_date": _date_text(row.get("documentDate")),
        "customer_name": row.get("customerName") or "",
        "amount": _num(row.get("totalAmountExcludingTax")),
        "external_document": row.get("externalDocumentNumber") or "",
        "status": row.get("status") or "",
    }


def _shipment(row: dict) -> dict:
    return {
        "number": row.get("number") or "",
        "order_number": row.get("orderNumber") or row.get("orderNo") or "",
        "posting_date": _date_text(row.get("postingDate")),
        "order_date": _date_text(row.get("orderDate")),
    }


def _receipt(row: dict) -> dict:
    return {
        "number": row.get("number") or "",
        "order_number": row.get("orderNumber") or "",
        "posting_date": _date_text(row.get("postingDate")),
        "vendor_number": row.get("vendorNumber") or "",
        "vendor_name": row.get("vendorName") or "",
    }


def _purchase_invoice(row: dict) -> dict:
    return {
        "number": row.get("number") or "",
        "order_number": row.get("orderNumber") or "",
        "posting_date": _date_text(row.get("postingDate")),
        "vendor_number": row.get("vendorNumber") or "",
        "vendor_name": row.get("vendorName") or "",
        "amount": _num(row.get("totalAmountExcludingTax")),
        "status": row.get("status") or "",
    }


def _item(row: dict) -> dict:
    return {
        "number": row.get("number") or "",
        "description": row.get("displayName") or "",
        "on_hand": _num(row.get("inventory")),
        "unit_cost": _num(row.get("unitCost")),
        "category": row.get("itemCategoryCode") or "",
        "reorder_point": None,
    }


def _customer(row: dict) -> dict:
    return {
        "number": row.get("number") or "",
        "name": row.get("displayName") or "",
        "balance": _num(row.get("balanceDue")),
    }


def resolve_range(start: Optional[date], end: Optional[date], today: Optional[date] = None) -> tuple[date, date]:
    today = today or date.today()
    end = end or today
    start = start or (end - timedelta(days=29))
    if start > end:
        raise ValueError("Choose an end date on or after the start date.")
    if (end - start).days > _MAX_RANGE_DAYS:
        raise ValueError("Choose a range of 800 days or less.")
    return start, end


kpi_dashboard_service = KpiDashboardService()
