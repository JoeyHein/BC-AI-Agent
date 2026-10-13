"""Requested receipt date for purchase orders created in the portal.

Business owner rule, 13 Oct 2026. Edit ``VENDOR_LEAD_RULES`` when a vendor's
lead time or Business Central vendor number changes. Match is the vendor
number first (exact, ignoring case), then the vendor name.

- Upwardor: PO date + 21 days. The vendor email says the warehouse date.
- Elton Manufacturing, Lynx, and Nice Canada (including Micanan / Nice):
  PO date + 14 days. The vendor email says the warehouse date.
- Every other vendor: ship when ready. The PO header is PO date + 2 days so
  the date is not left blank (BC's empty date is 0001-01-01). The vendor
  email says "Please ship when ready."

PO date for a new purchase order is the order date Business Central assigns.
When that date is not on the create response yet, the base is today in
America/Edmonton (the company timezone). The one-off Draft backfill counts
from today on purpose, instead of from an old order date.

This does not change sales-order requested delivery dates.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

BUSINESS_TZ = ZoneInfo("America/Edmonton")

# BC stores an empty date as 0001-01-01. Treat that, and anything before the
# company existed, as "no date".
_EARLIEST_REAL_YEAR = 1900


@dataclass(frozen=True)
class VendorLeadRule:
    """One row of the lead-time table.

    ``vendor_numbers`` are BC vendor numbers (``UPW``, ``ELT``, ``LYNX``).
    ``name_contains`` is matched against the vendor name after it is uppercased
    and punctuation is turned into spaces. A single word must be a whole word
    (``NICE`` matches "Nice Canada", not "Bernice"). A phrase (``NICE CANADA``)
    matches anywhere in that normalized name.
    """

    key: str
    label: str
    days: int
    ship_when_ready: bool
    vendor_numbers: tuple[str, ...]
    name_contains: tuple[str, ...]


# First match wins. Put the more specific vendor above a name that could
# also appear in another card.
VENDOR_LEAD_RULES: tuple[VendorLeadRule, ...] = (
    VendorLeadRule(
        key="upwardor",
        label="Upwardor",
        days=21,
        ship_when_ready=False,
        vendor_numbers=("UPW",),
        name_contains=("UPWARDOR", "UPW"),
    ),
    VendorLeadRule(
        key="elton",
        label="Elton Manufacturing",
        days=14,
        ship_when_ready=False,
        vendor_numbers=("ELT",),
        name_contains=("ELTON", "ELT"),
    ),
    VendorLeadRule(
        key="lynx",
        label="Lynx",
        days=14,
        ship_when_ready=False,
        vendor_numbers=("LYNX",),
        name_contains=("LYNX",),
    ),
    VendorLeadRule(
        key="nice_canada",
        label="Nice Canada",
        days=14,
        ship_when_ready=False,
        # Add the BC vendor number when the vendor card number is confirmed.
        # Names cover Nice Canada and the Micanan / Nice operator line.
        vendor_numbers=(),
        name_contains=("NICE CANADA", "MICANAN", "NICE"),
    ),
)

SHIP_WHEN_READY = VendorLeadRule(
    key="ship_when_ready",
    label="Ship when ready",
    days=2,
    ship_when_ready=True,
    vendor_numbers=(),
    name_contains=(),
)


@dataclass(frozen=True)
class ReceiptPlan:
    """The date to write on the purchase-order header, and why."""

    rule: VendorLeadRule
    po_date: date
    requested_receipt_date: date

    def public_dict(self) -> dict:
        return {
            "requested_receipt_date": self.requested_receipt_date.isoformat(),
            "receipt_base_date": self.po_date.isoformat(),
            "receipt_lead_days": self.rule.days,
            "receipt_rule": self.rule.key,
            "ship_when_ready": self.rule.ship_when_ready,
        }

    def email_line(self) -> str:
        return email_line(self.rule, self.requested_receipt_date)


def business_today() -> date:
    """Today in the company timezone. Lead time is calendar days, not business days."""
    return datetime.now(BUSINESS_TZ).date()


def _norm(text: Optional[str]) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", " ", (text or "").upper())
    return " ".join(cleaned.split())


def _name_matches(normalized_name: str, needle: str) -> bool:
    needle = _norm(needle)
    if not needle or not normalized_name:
        return False
    if " " in needle:
        return needle in normalized_name
    return f" {needle} " in f" {normalized_name} "


def parse_po_date(value: Any) -> Optional[date]:
    """A real calendar date, or None for blank / BC's 0001-01-01 sentinel."""
    if value is None or value is False:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return None if value.year < _EARLIEST_REAL_YEAR else value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return None
    if parsed.year < _EARLIEST_REAL_YEAR:
        return None
    return parsed


def match_vendor_lead_time(vendor_no: Optional[str], vendor_name: Optional[str]) -> VendorLeadRule:
    """Lead-time row for this vendor. Unknown vendors ship when ready."""
    number = (vendor_no or "").strip().upper()
    if number:
        for rule in VENDOR_LEAD_RULES:
            if number in {item.upper() for item in rule.vendor_numbers}:
                return rule
    name = _norm(vendor_name)
    if name:
        for rule in VENDOR_LEAD_RULES:
            if any(_name_matches(name, needle) for needle in rule.name_contains):
                return rule
    return SHIP_WHEN_READY


def requested_receipt_on(vendor_no: Optional[str], vendor_name: Optional[str], po_date: date) -> ReceiptPlan:
    rule = match_vendor_lead_time(vendor_no, vendor_name)
    return ReceiptPlan(
        rule=rule,
        po_date=po_date,
        requested_receipt_date=po_date + timedelta(days=rule.days),
    )


def receipt_plan_for_new_po(vendor_no: Optional[str], vendor_name: Optional[str]) -> ReceiptPlan:
    """Lead time counted from today. Callers replace this when BC returns another order date."""
    return requested_receipt_on(vendor_no, vendor_name, business_today())


def format_warehouse_date(value: date) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def email_line(rule: VendorLeadRule, receipt: Optional[date]) -> str:
    """The sentence the vendor PO email adds for this rule.

    Named vendors get the warehouse date. Every other vendor is asked to ship
    when ready, even though the header still carries PO date + 2 days.
    """
    if rule.ship_when_ready or receipt is None:
        return "Please ship when ready."
    return f"Required in our warehouse by {format_warehouse_date(receipt)}."


def sentence_for_vendor(
    vendor_no: Optional[str],
    vendor_name: Optional[str],
    requested_receipt_date: Any = None,
    order_date: Any = None,
    *,
    today: Optional[date] = None,
) -> str:
    """Email sentence from a vendor and the dates already known.

    A real requested-receipt date wins. When the header is still blank, a
    named vendor's date is counted from the PO order date, or from today when
    the order date is blank too.
    """
    rule = match_vendor_lead_time(vendor_no, vendor_name)
    if rule.ship_when_ready:
        return email_line(rule, None)
    receipt = parse_po_date(requested_receipt_date)
    if receipt is None:
        base = parse_po_date(order_date) or today or business_today()
        receipt = base + timedelta(days=rule.days)
    return email_line(rule, receipt)


def create_purchase_order_with_receipt(
    bc_client: Any,
    vendor_no: Optional[str],
    vendor_name: Optional[str],
    plan: Optional[ReceiptPlan] = None,
) -> tuple[dict, ReceiptPlan]:
    """Create a BC purchase order and set requestedReceiptDate from the rule.

    ``vendorName`` is not sent: api/v2.0 rejects it on create. The receipt
    date is sent on the create. If Business Central's order date is a different
    day, or the create response still has a blank receipt date, the header is
    patched so the stored date is that order date plus the lead time.
    """
    plan = plan or receipt_plan_for_new_po(vendor_no, vendor_name)
    bc_po = bc_client.create_purchase_order({
        "vendorNumber": vendor_no or "",
        "requestedReceiptDate": plan.requested_receipt_date.isoformat(),
    })
    if not isinstance(bc_po, dict):
        raise RuntimeError(f"BC did not return a purchase order: {bc_po!r}")

    assigned = parse_po_date(bc_po.get("orderDate"))
    if assigned and assigned != plan.po_date:
        plan = requested_receipt_on(vendor_no, vendor_name, assigned)

    if _receipt_already_stored(bc_po, plan):
        logger.info(
            "Purchase order %s requested receipt %s (%s, +%s days)",
            bc_po.get("number") or bc_po.get("id"),
            plan.requested_receipt_date.isoformat(),
            plan.rule.key,
            plan.rule.days,
        )
        return bc_po, plan

    po_id = bc_po.get("id")
    if not po_id:
        raise RuntimeError(
            "BC purchase order has no id; requested receipt date was not confirmed"
        )
    updated = bc_client.update_purchase_order(po_id, {
        "requestedReceiptDate": plan.requested_receipt_date.isoformat(),
    })
    if isinstance(updated, dict) and updated:
        bc_po = {**bc_po, **updated}
    if not _receipt_already_stored(bc_po, plan):
        fresh = bc_client.get_purchase_order(po_id)
        if isinstance(fresh, dict) and fresh:
            bc_po = {**bc_po, **fresh}
    if not _receipt_already_stored(bc_po, plan):
        raise RuntimeError(
            "Business Central did not store requested receipt date "
            f"{plan.requested_receipt_date.isoformat()} on "
            f"{bc_po.get('number') or po_id}"
        )
    logger.info(
        "Patched purchase order %s requested receipt %s (%s, +%s days from %s)",
        bc_po.get("number") or po_id,
        plan.requested_receipt_date.isoformat(),
        plan.rule.key,
        plan.rule.days,
        plan.po_date.isoformat(),
    )
    return bc_po, plan


def _receipt_already_stored(bc_po: dict, plan: ReceiptPlan) -> bool:
    if "requestedReceiptDate" not in bc_po:
        return False
    return parse_po_date(bc_po.get("requestedReceiptDate")) == plan.requested_receipt_date
