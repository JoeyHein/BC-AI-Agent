"""Read-only posted sales invoice lines for staff analysis.

Lines are joined to invoice headers because the BC line entity has no
posting date. The header postingDate window is what gets filtered.
"""

import logging
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

_CUSTOMER_NO = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
_WINDOW_TTL_SECONDS = 300
_CATALOG_TTL_SECONDS = 600

# (start, end, customer) -> (stored_at, payload)
_WINDOW_CACHE: Dict[Tuple[str, str, Optional[str]], Tuple[float, Dict[str, Any]]] = {}
_CATALOG_CACHE: Optional[Tuple[float, Dict[str, Any]]] = None


def clear_sales_invoice_cache() -> None:
    """Drop in-process caches. Tests and a forced refresh call this."""
    global _CATALOG_CACHE
    _WINDOW_CACHE.clear()
    _CATALOG_CACHE = None


def normalize_window(
    start_date: date,
    end_date: date,
    customer_no: Optional[str],
) -> Tuple[str, str, Optional[str]]:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    customer = (customer_no or "").strip() or None
    if customer is not None and not _CUSTOMER_NO.fullmatch(customer):
        raise ValueError("customer_no contains unsupported characters")
    return start_date.isoformat(), end_date.isoformat(), customer


def _money(line: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        if key in line and line.get(key) is not None:
            return line.get(key)
    return None


def _line_number(line: Dict[str, Any]) -> Optional[int]:
    for key in ("sequence", "lineNumber", "lineNo"):
        value = line.get(key)
        if value is not None:
            return value
    return None


def flatten_invoice_lines(
    invoices: List[Dict[str, Any]],
    category_by_item: Dict[str, Optional[str]],
) -> List[Dict[str, Any]]:
    """One row per invoice line, with header date, customer, and area copied on."""
    rows: List[Dict[str, Any]] = []
    for inv in invoices:
        header = {
            "invoiceNo": inv.get("number"),
            "invoiceId": inv.get("id"),
            "invoiceDate": inv.get("invoiceDate"),
            "postingDate": inv.get("postingDate"),
            "customerNo": inv.get("customerNumber"),
            "customerName": inv.get("customerName"),
            "sellToCity": inv.get("sellToCity"),
            "sellToState": inv.get("sellToState"),
            "sellToPostCode": inv.get("sellToPostCode"),
            "sellToCountry": inv.get("sellToCountry"),
            "shipToCity": inv.get("shipToCity"),
            "shipToState": inv.get("shipToState"),
            "shipToPostCode": inv.get("shipToPostCode"),
            "shipToCountry": inv.get("shipToCountry"),
        }
        for line in inv.get("salesInvoiceLines") or []:
            item_no = (line.get("lineObjectNumber") or "").strip() or None
            rows.append({
                **header,
                "lineNo": _line_number(line),
                "lineType": line.get("lineType"),
                "itemNo": item_no,
                "description": line.get("description"),
                "quantity": line.get("quantity"),
                "unitOfMeasure": line.get("unitOfMeasureCode"),
                "unitPrice": line.get("unitPrice"),
                "amountExcludingTax": _money(line, "amountExcludingTax", "netAmount"),
                "amountIncludingTax": _money(
                    line, "amountIncludingTax", "netAmountIncludingTax"
                ),
                "itemCategoryCode": category_by_item.get(item_no) if item_no else None,
            })
    rows.sort(key=lambda r: (
        r.get("postingDate") or "",
        r.get("invoiceNo") or "",
        r.get("lineNo") if isinstance(r.get("lineNo"), (int, float)) else 0,
    ))
    return rows


def _item_numbers(invoices: List[Dict[str, Any]]) -> List[str]:
    found: List[str] = []
    seen = set()
    for inv in invoices:
        for line in inv.get("salesInvoiceLines") or []:
            number = (line.get("lineObjectNumber") or "").strip()
            if number and number not in seen:
                seen.add(number)
                found.append(number)
    return found


def _load_window(start: str, end: str, customer: Optional[str]) -> Dict[str, Any]:
    key = (start, end, customer)
    now = time.monotonic()
    cached = _WINDOW_CACHE.get(key)
    if cached and (now - cached[0]) < _WINDOW_TTL_SECONDS:
        return cached[1]

    invoices, complete = bc_client.get_sales_invoices_with_lines(
        start_date=start,
        end_date=end,
        customer_number=customer,
    )
    if not complete and not invoices:
        raise RuntimeError("Business Central did not return sales invoices")

    category_by_item: Dict[str, Optional[str]] = {}
    item_nos = _item_numbers(invoices)
    if item_nos:
        try:
            category_by_item = bc_client.get_item_category_codes(item_nos)
        except Exception as e:
            logger.warning(f"Item category lookup failed; lines will omit it: {e}")

    payload = {
        "totalInvoices": len(invoices),
        "complete": complete,
        "lines": flatten_invoice_lines(invoices, category_by_item),
    }
    _WINDOW_CACHE[key] = (now, payload)
    return payload


def get_invoice_lines(
    start_date: date,
    end_date: date,
    customer_no: Optional[str] = None,
    page: int = 1,
    page_size: int = 200,
) -> Dict[str, Any]:
    """Flattened invoice lines for the window, one page at a time.

    The BC pull is cached briefly so paging does not re-download the window.
    ``totalLines`` / ``totalInvoices`` describe the whole window, not the page.
    ``complete`` is false when BC paging stopped early (nothing is dropped
    silently at 500).
    """
    start, end, customer = normalize_window(start_date, end_date, customer_no)
    window = _load_window(start, end, customer)
    rows = window["lines"]
    total = len(rows)
    offset = (page - 1) * page_size
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "startDate": start,
        "endDate": end,
        "customerNo": customer,
        "page": page,
        "pageSize": page_size,
        "totalInvoices": window["totalInvoices"],
        "totalLines": total,
        "totalPages": total_pages,
        "complete": window["complete"],
        "lines": rows[offset:offset + page_size],
    }


def get_item_category_catalog() -> Dict[str, Any]:
    """BC item categories plus item number -> category code and description.

    ``parentCategoryCode`` is null when this tenant's itemCategories entity
    does not carry a parent (the v2.0 category resource often has only code
    and displayName).
    """
    global _CATALOG_CACHE
    now = time.monotonic()
    if _CATALOG_CACHE and (now - _CATALOG_CACHE[0]) < _CATALOG_TTL_SECONDS:
        return _CATALOG_CACHE[1]

    categories = bc_client.get_item_categories()
    items = bc_client.get_all_items(select="number,itemCategoryCode")

    by_code: Dict[str, Optional[str]] = {}
    category_rows = []
    for cat in categories:
        code = cat.get("code")
        description = cat.get("displayName") or cat.get("description")
        parent = cat.get("parentCategoryCode") or None
        category_rows.append({
            "code": code,
            "description": description,
            "parentCategoryCode": parent,
        })
        if code:
            by_code[code] = description

    item_rows = []
    for item in items:
        number = item.get("number")
        if not number:
            continue
        code = item.get("itemCategoryCode") or None
        item_rows.append({
            "itemNo": number,
            "categoryCode": code,
            "categoryDescription": by_code.get(code) if code else None,
        })

    payload = {
        "categoryCount": len(category_rows),
        "itemCount": len(item_rows),
        "categories": category_rows,
        "items": item_rows,
    }
    # Don't pin a failed empty pull (BC errors degrade to []) for the TTL.
    if category_rows or item_rows:
        _CATALOG_CACHE = (now, payload)
    return payload
