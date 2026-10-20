"""Read-only Business Central lookups for staff and the service key.

Every route is GET. Creating, converting, posting, and emailing stay on
the existing write routes, which the service key cannot call.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.admin_quotes import _lookup_bc_quote, normalize_staff_quote_ref
from app.api.staff_principal import require_staff
from app.db.database import get_db
from app.db.models import BCCustomer, User
from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bc", tags=["bc-read"])

_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_EXPANDED_LINE_KEYS = {
    "salesQuoteLines",
    "salesOrderLines",
    "purchaseOrderLines",
    "salesInvoiceLines",
    "purchaseInvoiceLines",
}


def public_record(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Drop OData control fields and expanded line collections."""
    out: Dict[str, Any] = {}
    for key, value in (row or {}).items():
        if "@" in key or key in _EXPANDED_LINE_KEYS:
            continue
        out[key] = value
    return out


def public_lines(lines: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Every line, including comments, in BC sequence order."""
    cleaned = [public_record(line) for line in (lines or [])]
    cleaned.sort(key=lambda line: line.get("sequence") or 0)
    return cleaned


def _bc_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except HTTPException:
        raise
    except requests.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.error("BC read failed: %s", exc)
        if status == 404:
            raise HTTPException(status_code=404, detail="Not found in Business Central") from exc
        raise HTTPException(
            status_code=502,
            detail=f"Business Central request failed: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("BC read failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Business Central request failed: {exc}",
        ) from exc


def _prefixed(raw: str, prefix: str) -> tuple[str, str]:
    """Return ('guid', uuid) or ('number', PREFIX######). Bare digits are padded."""
    value = (raw or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Document number is required")
    if _GUID_RE.fullmatch(value):
        return "guid", value
    upper = value.upper()
    if upper.startswith(prefix):
        return "number", upper
    if value.isdigit():
        return "number", f"{prefix}{int(value):06d}"
    return "number", upper


def _require_posted(doc: Dict[str, Any], number: str) -> Dict[str, Any]:
    status = (doc.get("status") or "").strip().lower()
    if status == "draft":
        raise HTTPException(
            status_code=404,
            detail=f"{number} is not a posted document",
        )
    return doc


_LINE_COLLECTION = {
    "salesQuotes": "salesQuoteLines",
    "salesOrders": "salesOrderLines",
    "purchaseOrders": "purchaseOrderLines",
    "salesInvoices": "salesInvoiceLines",
    "purchaseInvoices": "purchaseInvoiceLines",
}


def _with_lines(header: Dict[str, Any], parent: str) -> Dict[str, Any]:
    doc_id = header.get("id")
    if not doc_id:
        raise HTTPException(status_code=502, detail="Business Central returned a document without an id")
    lines_name = _LINE_COLLECTION[parent]
    lines = _bc_call(
        bc_client.get_document_lines,
        f"{parent}({doc_id})/{lines_name}",
    )
    body = public_record(header)
    body["lines"] = public_lines(lines)
    return body


def _page_start(skip: int, offset: Optional[int]) -> int:
    return skip if offset is None else offset


@router.get("/sales-quotes")
def list_sales_quotes(
    search: Optional[str] = Query(None, description="Substring of the quote number"),
    skip: int = Query(0, ge=0),
    offset: Optional[int] = Query(None, ge=0, description="Alias for skip"),
    top: int = Query(50, ge=1, le=200),
    _user: User = Depends(require_staff),
):
    """Paged sales quotes, newest number first. Search matches the quote number."""
    start = _page_start(skip, offset)
    rows = _bc_call(bc_client.list_sales_quotes, search=search, skip=start, top=top)
    return {
        "skip": start,
        "top": top,
        "count": len(rows),
        "quotes": [public_record(row) for row in rows],
    }


@router.get("/sales-quotes/{quote_number}")
def get_sales_quote(
    quote_number: str,
    _user: User = Depends(require_staff),
):
    """Quote header plus every line, including comment lines."""
    kind, value = normalize_staff_quote_ref(quote_number)
    quote = _lookup_bc_quote(kind, value)
    return _with_lines(quote, "salesQuotes")


@router.get("/sales-orders/{order_number}")
def get_sales_order(
    order_number: str,
    _user: User = Depends(require_staff),
):
    """Sales order header plus every line."""
    kind, value = _prefixed(order_number, "SO-")
    if kind == "guid":
        order = _bc_call(bc_client.get_sales_order, value)
    else:
        order = _bc_call(bc_client.get_sales_order_by_number, value)
    if not order:
        raise HTTPException(status_code=404, detail=f"Sales order {value} not found")
    return _with_lines(order, "salesOrders")


@router.get("/purchase-orders/{po_number}")
def get_purchase_order(
    po_number: str,
    _user: User = Depends(require_staff),
):
    """Purchase order header plus every line. Any status. Does not change the PO."""
    kind, value = _prefixed(po_number, "PO-")
    if kind == "guid":
        po = _bc_call(bc_client.get_purchase_order, value)
    else:
        po = _bc_call(bc_client.get_purchase_order_by_number, value)
    if not po:
        raise HTTPException(status_code=404, detail=f"Purchase order {value} not found")
    return _with_lines(po, "purchaseOrders")


def _customer_from_cache(row: BCCustomer) -> Dict[str, Any]:
    meta = row.customer_metadata or {}
    return {
        "bc_customer_id": row.bc_customer_id,
        "customer_number": meta.get("number"),
        "company_name": row.company_name,
        "contact_name": row.contact_name,
        "email": row.email,
        "phone": row.phone,
        "bc_price_group": row.bc_price_group,
        "pricing_tier": row.pricing_tier,
        "price_multiplier": row.price_multiplier,
        "blocked": meta.get("blocked") or "",
    }


def _customer_from_bc(live: Dict[str, Any]) -> Dict[str, Any]:
    number = live.get("number")
    group = None
    if number:
        group = bc_client.get_customer_price_group(number)
    return {
        "bc_customer_id": live.get("id"),
        "customer_number": number,
        "company_name": live.get("displayName"),
        "contact_name": live.get("contactName") or live.get("displayName"),
        "email": live.get("email"),
        "phone": live.get("phoneNumber"),
        "bc_price_group": group,
        "pricing_tier": None,
        "price_multiplier": live.get("priceMultiplierPercent"),
        "blocked": (live.get("blocked") or "").strip(),
    }


@router.get("/customers")
def list_customers(
    search: Optional[str] = Query(None, description="Name, email, customer number, or price group"),
    skip: int = Query(0, ge=0),
    offset: Optional[int] = Query(None, ge=0),
    top: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(require_staff),
):
    """Cached BC customers, including price group. A number miss falls through to BC."""
    start = _page_start(skip, offset)
    query = db.query(BCCustomer).filter(~BCCustomer.bc_customer_id.like("TEMP-%"))
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        query = query.filter(or_(
            BCCustomer.company_name.ilike(like),
            BCCustomer.contact_name.ilike(like),
            BCCustomer.email.ilike(like),
            BCCustomer.bc_price_group.ilike(like),
            BCCustomer.bc_customer_id.ilike(like),
        ))
    rows = query.order_by(BCCustomer.company_name.asc()).offset(start).limit(top).all()
    customers = [_customer_from_cache(row) for row in rows]
    known_ids = {row.bc_customer_id for row in rows}
    if term:
        number_hits = [
            row for row in db.query(BCCustomer).filter(
                ~BCCustomer.bc_customer_id.like("TEMP-%")
            ).all()
            if term.lower() in str((row.customer_metadata or {}).get("number") or "").lower()
            and row.bc_customer_id not in known_ids
        ]
        for row in number_hits:
            if len(customers) >= top:
                break
            customers.append(_customer_from_cache(row))
            known_ids.add(row.bc_customer_id)
        if not any(
            (c.get("customer_number") or "").lower() == term.lower() for c in customers
        ):
            try:
                live = bc_client.get_customer_by_number(term)
            except Exception:
                logger.warning("Live customer lookup failed for %s", term, exc_info=True)
                live = None
            if live and live.get("id") not in known_ids:
                customers.insert(0, _customer_from_bc(live))
    return {"skip": start, "top": top, "count": len(customers), "customers": customers[:top]}


@router.get("/customers/{customer_number}")
def get_customer(
    customer_number: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_staff),
):
    """One customer by BC number, with price group."""
    number = (customer_number or "").strip()
    if not number:
        raise HTTPException(status_code=400, detail="Customer number is required")
    cached = [
        row for row in db.query(BCCustomer).all()
        if str((row.customer_metadata or {}).get("number") or "").lower() == number.lower()
    ]
    if cached:
        return _customer_from_cache(cached[0])
    live = _bc_call(bc_client.get_customer_by_number, number)
    if not live:
        raise HTTPException(status_code=404, detail=f"Customer {number} not found")
    return _customer_from_bc(live)


def _item_out(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "number": item.get("number"),
        "displayName": item.get("displayName"),
        "unitPrice": item.get("unitPrice"),
        "unitCost": item.get("unitCost"),
        "inventory": item.get("inventory"),
        "baseUnitOfMeasureCode": item.get("baseUnitOfMeasureCode"),
        "type": item.get("type"),
        "itemCategoryCode": item.get("itemCategoryCode"),
    }


@router.get("/items")
def search_items(
    search: str = Query(..., min_length=1, description="Item number or name"),
    top: int = Query(50, ge=1, le=100),
    _user: User = Depends(require_staff),
):
    """Items by number or name, with unit price, unit cost, and on-hand quantity."""
    items = _bc_call(bc_client.search_items_for_read, search, top)
    return {"count": len(items), "items": [_item_out(item) for item in items]}


@router.get("/items/{item_number}")
def get_item(
    item_number: str,
    _user: User = Depends(require_staff),
):
    """One item by number, with unit price, unit cost, and on-hand quantity."""
    wanted = (item_number or "").strip()
    items = _bc_call(bc_client.search_items, wanted)
    match = next(
        (item for item in items if (item.get("number") or "").upper() == wanted.upper()),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail=f"Item {wanted} not found")
    return _item_out(match)


@router.get("/vendors")
def list_vendors(
    top: int = Query(500, ge=1, le=1000),
    _user: User = Depends(require_staff),
):
    """Vendor cards from Business Central."""
    vendors = _bc_call(bc_client.get_vendors, top=top)
    cleaned = [public_record(vendor) for vendor in vendors if vendor.get("number")]
    return {"count": len(cleaned), "vendors": cleaned}


@router.get("/sales-invoices/{invoice_number}")
def get_posted_sales_invoice(
    invoice_number: str,
    _user: User = Depends(require_staff),
):
    """Posted sales invoice header plus lines. Draft invoices are not returned."""
    raw = (invoice_number or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Invoice number is required")
    doc = _bc_call(bc_client.get_sales_invoice_by_number, raw)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Invoice {raw} not found")
    _require_posted(doc, raw)
    return _with_lines(doc, "salesInvoices")


@router.get("/purchase-invoices/{invoice_number}")
def get_posted_purchase_invoice(
    invoice_number: str,
    _user: User = Depends(require_staff),
):
    """Posted purchase invoice header plus lines. Draft invoices are not returned."""
    raw = (invoice_number or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Invoice number is required")
    doc = _bc_call(bc_client.get_purchase_invoice_by_number, raw)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Invoice {raw} not found")
    _require_posted(doc, raw)
    return _with_lines(doc, "purchaseInvoices")


@router.get("/sales-price-lines")
def sales_price_lines(
    item_no: str = Query(..., min_length=1),
    source_type: int = Query(0, ge=0, le=2, description="0 all customers, 1 customer, 2 price group"),
    source_no: str = Query("", description="Customer number or price group code"),
    qty: float = Query(1.0, ge=0),
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD"),
    _user: User = Depends(require_staff),
):
    """Sales price list lines for one item."""
    result = _bc_call(
        bc_client.get_sales_price_lines,
        item_no=item_no,
        source_type=source_type,
        source_no=source_no,
        qty=qty,
        as_of_date=as_of,
    )
    return {
        "item_no": item_no,
        "source_type": source_type,
        "source_no": source_no,
        "qty": qty,
        "as_of": as_of,
        "available": result.get("available"),
        "error": result.get("error"),
        "lines": result.get("entries") or [],
    }


@router.get("/purchase-price-lines")
def purchase_price_lines(
    item_no: str = Query(..., min_length=1),
    vendor_no: str = Query("", description="Vendor number, for example UPW"),
    unit_of_measure: str = Query("", description="Unit of measure code"),
    qty: float = Query(1.0, ge=0),
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD, usually the PO order date"),
    _user: User = Depends(require_staff),
):
    """Vendor purchase price list lines for one item. Read-only."""
    result = _bc_call(
        bc_client.get_purchase_price_lines,
        item_no=item_no,
        vendor_no=vendor_no,
        unit_of_measure=unit_of_measure,
        qty=qty,
        as_of_date=as_of,
    )
    return {
        "item_no": item_no,
        "vendor_no": vendor_no,
        "unit_of_measure": unit_of_measure,
        "qty": qty,
        "as_of": as_of,
        "available": result.get("available"),
        "error": result.get("error"),
        "lines": result.get("entries") or [],
    }
