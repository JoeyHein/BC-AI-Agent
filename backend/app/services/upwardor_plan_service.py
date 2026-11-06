"""Read-only Upwardor actuals for the payable plan.

Vendor balance and posted purchase invoices come from Business Central
api/v2.0. Payments are read from a vendor-ledger feed when one is published.
Nothing in this module writes to Business Central.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

import requests

from app.config import settings
from app.db.models import AppSettings
from app.integrations.bc.client import bc_client
from app.services.upwardor_plan import (
    EDMONTON,
    GNB_PO_NUMBER,
    PLAN_START,
    PLAN_WEEKS,
    build_forecast,
    merge_actuals,
    money,
    resolve_lever_choices,
    week_state,
)

logger = logging.getLogger(__name__)

SETTINGS_KEY = "upwardor_plan_overrides"
VENDOR_NUMBERS = ("UPW", "UPWARDOR")
PLAN_START_ISO = PLAN_START.isoformat()
_CACHE_SECONDS = 60
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "snapshot": None}


def _configured() -> bool:
    return bool(
        settings.BC_TENANT_ID
        and settings.BC_CLIENT_ID
        and settings.BC_CLIENT_SECRET
        and settings.BC_COMPANY_ID
    )


def empty_snapshot(error: str) -> dict[str, Any]:
    return {
        "balance": None,
        "balance_source": "unavailable",
        "weeks": {},
        "invoices_known": False,
        "payments_known": False,
        "credits_known": False,
        "purchase_orders": [],
        "errors": [error] if error else [],
    }


def fetch_bc_snapshot(now: Optional[float] = None) -> dict[str, Any]:
    """Cached read of balance, invoices, payments, and open Upwardor POs."""
    clock = time.time() if now is None else now
    with _cache_lock:
        cached = _cache.get("snapshot")
        if cached is not None and clock - float(_cache.get("at") or 0) < _CACHE_SECONDS:
            return cached
    snapshot = _fetch_bc_snapshot()
    with _cache_lock:
        _cache["at"] = clock
        _cache["snapshot"] = snapshot
    return snapshot


def clear_snapshot_cache() -> None:
    with _cache_lock:
        _cache["at"] = 0.0
        _cache["snapshot"] = None


def _fetch_bc_snapshot() -> dict[str, Any]:
    if not _configured():
        return empty_snapshot("Business Central is not configured on this server.")
    errors: list[str] = []
    try:
        vendor = _find_vendor()
    except Exception as exc:
        logger.warning("Upwardor vendor lookup failed: %s", exc)
        return empty_snapshot(f"Vendor lookup failed: {exc}")

    if vendor is None:
        errors.append("No Upwardor vendor (UPW) was returned by Business Central.")
        vendor_no = "UPW"
        balance = None
    else:
        vendor_no = str(vendor.get("number") or "UPW")
        raw_balance = vendor.get("balanceDue")
        balance = money(raw_balance) if raw_balance is not None else None

    weeks: dict[str, dict] = {}
    invoices_known = False
    credit_memos: list[tuple[date, float, str]] = []
    try:
        invoice_rows, basis = _purchase_invoices(vendor_no)
        invoices_known = True
        credit_memos = _bucket_invoices(weeks, invoice_rows, basis)
    except Exception as exc:
        logger.warning("Upwardor purchase invoices failed: %s", exc)
        errors.append(f"Purchase invoices were not read: {exc}")

    payments_known = False
    credits_known = False
    try:
        ledger_rows = _vendor_ledger(vendor_no)
        if ledger_rows is not None:
            payments_known = True
            credits_known = True
            _bucket_ledger(weeks, ledger_rows, use_invoices=not invoices_known)
    except Exception as exc:
        logger.warning("Upwardor vendor ledger failed: %s", exc)
        errors.append(f"Vendor ledger was not read: {exc}")

    if not credits_known:
        for posted, amount, source in credit_memos:
            key = _monday(posted).isoformat()
            slot = weeks.setdefault(key, {})
            slot["credits"] = float(slot.get("credits") or 0) + amount
            slot["credits_source"] = source

    if invoices_known or payments_known or credits_known:
        _fill_elapsed_zeros(
            weeks,
            invoices=invoices_known,
            payments=payments_known,
            credits=credits_known,
        )

    purchase_orders: list[dict] = []
    try:
        purchase_orders = _purchase_orders(vendor_no)
    except Exception as exc:
        logger.warning("Upwardor purchase orders failed: %s", exc)
        errors.append(f"Purchase orders were not read: {exc}")

    return {
        "balance": balance,
        "balance_source": "business_central" if balance is not None else "unavailable",
        "weeks": weeks,
        "invoices_known": invoices_known,
        "payments_known": payments_known,
        "credits_known": credits_known,
        "purchase_orders": purchase_orders,
        "errors": errors,
    }


def _company_path(relative: str) -> str:
    return f"companies({settings.BC_COMPANY_ID})/{relative}"


def _odata_get(relative: str) -> dict:
    """GET one api/v2.0 collection. Raises on HTTP errors so the caller can record them."""
    url = f"{bc_client.base_url}/{_company_path(relative)}"
    rows: list[dict] = []
    while url:
        token = bc_client._get_access_token()
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:240]}")
        payload = response.json()
        rows.extend(payload.get("value") or [])
        url = payload.get("@odata.nextLink")
    return {"value": rows}


def _find_vendor() -> Optional[dict]:
    for number in VENDOR_NUMBERS:
        safe = number.replace("'", "''")
        payload = _odata_get(
            "vendors?$select=number,displayName,balanceDue"
            f"&$filter=number eq '{safe}'"
        )
        rows = payload.get("value") or []
        if rows:
            return rows[0]
    payload = _odata_get("vendors?$select=number,displayName,balanceDue&$top=500")
    for row in payload.get("value") or []:
        name = str(row.get("displayName") or "").upper()
        number = str(row.get("number") or "").upper()
        if "UPWARD" in name or number in VENDOR_NUMBERS:
            return row
    return None


def _purchase_invoices(vendor_no: str) -> tuple[list[dict], str]:
    safe = vendor_no.replace("'", "''")
    payload = _odata_get(
        "purchaseInvoices?$select=number,postingDate,vendorNumber,vendorName,"
        "totalAmountIncludingTax,totalAmountExcludingTax,status,orderNumber"
        f"&$filter=vendorNumber eq '{safe}' and postingDate ge {PLAN_START_ISO}"
        " and (status eq 'Open' or status eq 'Paid')"
    )
    rows = payload.get("value") or []
    basis = "including_tax"
    if rows and rows[0].get("totalAmountIncludingTax") is None:
        basis = "excluding_tax"
    return rows, basis


def _bucket_invoices(weeks: dict[str, dict], rows: list[dict], basis: str) -> list[tuple[date, float, str]]:
    """Positive invoices hit the buy total. Negatives are held back so a vendor
    ledger credit memo is not counted twice."""
    source = "business_central" if basis == "including_tax" else "business_central_excluding_tax"
    credits: list[tuple[date, float, str]] = []
    for row in rows:
        posted = _parse_date(row.get("postingDate"))
        if posted is None:
            continue
        amount = row.get("totalAmountIncludingTax")
        if amount is None:
            amount = row.get("totalAmountExcludingTax") or 0
        amount = float(amount or 0)
        if amount < 0:
            credits.append((posted, abs(amount), source))
            continue
        key = _monday(posted).isoformat()
        slot = weeks.setdefault(key, {})
        slot["invoices"] = float(slot.get("invoices") or 0) + amount
        slot["invoices_source"] = source
    return credits


def _vendor_ledger(vendor_no: str) -> Optional[list[dict]]:
    """Return ledger rows, or None when no ledger feed is published."""
    safe = vendor_no.replace("'", "''")
    api_candidates = (
        "vendorLedgerEntries?$filter="
        f"vendorNumber eq '{safe}' and postingDate ge {PLAN_START_ISO}",
        "vendorLedgerEntries?$filter="
        f"vendorNo eq '{safe}' and postingDate ge {PLAN_START_ISO}",
    )
    for relative in api_candidates:
        try:
            payload = _odata_get(relative)
        except Exception as exc:
            message = str(exc).lower()
            if "404" in message or "not found" in message:
                continue
            raise
        return payload.get("value") or []

    if not bc_client.odata_url:
        return None
    try:
        company = bc_client._odata_v4_company_segment()
    except Exception as exc:
        logger.warning("Upwardor OData company segment failed: %s", exc)
        return None
    token = bc_client._get_access_token()
    for entity in ("VendorLedgerEntries", "Vendor_Ledger_Entries"):
        url = (
            f"{bc_client.odata_url}/{company}/{entity}"
            f"?$filter=Vendor_No eq '{safe}' and Posting_Date ge {PLAN_START_ISO}"
        )
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30,
        )
        if response.status_code == 404:
            continue
        if response.status_code >= 400:
            logger.info("Upwardor OData %s returned HTTP %s", entity, response.status_code)
            continue
        return (response.json() or {}).get("value") or []
    return None


def _bucket_ledger(weeks: dict[str, dict], rows: list[dict], *, use_invoices: bool) -> None:
    for row in rows:
        posted = _parse_date(row.get("postingDate") or row.get("Posting_Date"))
        if posted is None:
            continue
        doc = str(row.get("documentType") or row.get("Document_Type") or "").strip().lower()
        raw = row.get("amount", row.get("Amount", row.get("Amount_LCY")))
        if raw is None:
            continue
        magnitude = abs(float(raw))
        key = _monday(posted).isoformat()
        slot = weeks.setdefault(key, {})
        if "payment" in doc:
            slot["payments"] = float(slot.get("payments") or 0) + magnitude
            slot["payments_source"] = "business_central_vendor_ledger"
        elif "credit" in doc:
            slot["credits"] = float(slot.get("credits") or 0) + magnitude
            slot["credits_source"] = "business_central_vendor_ledger"
        elif "refund" in doc:
            slot["payments"] = float(slot.get("payments") or 0) - magnitude
            slot["payments_source"] = "business_central_vendor_ledger"
        elif use_invoices and "invoice" in doc:
            slot["invoices"] = float(slot.get("invoices") or 0) + magnitude
            slot["invoices_source"] = "business_central_vendor_ledger"


def _fill_elapsed_zeros(weeks: dict[str, dict], *, invoices: bool, payments: bool, credits: bool) -> None:
    """A successful feed with no rows is a real zero for weeks already underway."""
    moment = datetime.now(EDMONTON)
    for week in PLAN_WEEKS:
        if week_state(week["week_of"], moment) == "future":
            continue
        key = week["week_of"].isoformat()
        slot = weeks.setdefault(key, {})
        if invoices and slot.get("invoices") is None:
            slot["invoices"] = 0
            slot["invoices_source"] = slot.get("invoices_source") or "business_central"
        if payments and slot.get("payments") is None:
            slot["payments"] = 0
            slot["payments_source"] = slot.get("payments_source") or "business_central_vendor_ledger"
        if credits and slot.get("credits") is None:
            slot["credits"] = 0
            slot["credits_source"] = slot.get("credits_source") or "business_central_vendor_ledger"


def _purchase_orders(vendor_no: str) -> list[dict]:
    safe = vendor_no.replace("'", "''")
    payload = _odata_get(
        "purchaseOrders?$select=number,status,orderDate,requestedReceiptDate,"
        "totalAmountIncludingTax,vendorNumber,vendorName"
        f"&$filter=vendorNumber eq '{safe}' and (status eq 'Open' or status eq 'Draft')"
    )
    rows = list(payload.get("value") or [])
    numbers = {str(row.get("number") or "") for row in rows}
    if GNB_PO_NUMBER not in numbers:
        extra = _odata_get(
            "purchaseOrders?$select=number,status,orderDate,requestedReceiptDate,"
            "totalAmountIncludingTax,vendorNumber,vendorName"
            f"&$filter=number eq '{GNB_PO_NUMBER}'"
        )
        rows.extend(extra.get("value") or [])
    public = []
    for row in rows:
        amount = row.get("totalAmountIncludingTax")
        public.append({
            "number": row.get("number"),
            "status": row.get("status"),
            "order_date": row.get("orderDate"),
            "requested_receipt_date": row.get("requestedReceiptDate"),
            "amount": money(amount) if amount is not None else None,
            "is_gnb": str(row.get("number") or "") == GNB_PO_NUMBER,
        })
    public.sort(key=lambda row: (not row["is_gnb"], str(row.get("number") or "")))
    return public


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def read_overrides(db) -> dict:
    if db is None:
        return {}
    row = db.query(AppSettings).filter(AppSettings.setting_key == SETTINGS_KEY).first()
    if row is None or not isinstance(row.setting_value, dict):
        return {}
    return row.setting_value


def write_overrides(db, payload: dict, user_id: Optional[int]) -> dict:
    row = db.query(AppSettings).filter(AppSettings.setting_key == SETTINGS_KEY).first()
    if row is None:
        row = AppSettings(
            setting_key=SETTINGS_KEY,
            setting_value=payload,
            description="Upwardor $500K plan lever status and staff actuals",
            updated_by=user_id,
        )
        db.add(row)
    else:
        row.setting_value = payload
        row.updated_by = user_id
    db.commit()
    return payload


def build_report(db, *, as_of: Optional[datetime] = None, snapshot: Optional[dict] = None) -> dict:
    """Plan, live actuals, and the reforecast. BC failures come back as notes, not a 500."""
    moment = as_of or datetime.now(EDMONTON)
    if snapshot is None:
        try:
            snapshot = fetch_bc_snapshot()
        except Exception as exc:
            logger.warning("Upwardor snapshot failed: %s", exc)
            snapshot = empty_snapshot(str(exc))
    overrides = read_overrides(db)
    actuals = merge_actuals(
        snapshot.get("weeks"),
        overrides,
        balance=snapshot.get("balance"),
        as_of=moment,
    )
    levers = resolve_lever_choices(
        overrides,
        snapshot.get("purchase_orders"),
        actuals,
        moment,
    )
    report = build_forecast(
        moment,
        actuals,
        levers,
        balance=snapshot.get("balance"),
        balance_source=snapshot.get("balance_source") or "unavailable",
        purchase_orders=snapshot.get("purchase_orders"),
        errors=list(snapshot.get("errors") or []),
    )
    report["can_edit"] = False
    return report
