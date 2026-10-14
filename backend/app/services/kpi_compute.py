"""Turn already-fetched Business Central and portal rows into KPI numbers.

This module does not call Business Central. The dashboard service fetches
and normalizes; tests call ``build_kpi_dashboard`` with plain dicts.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.services.kpi_product_map import (
    ProductMap,
    classify_operator,
    classify_product_line,
    is_freight,
    load_product_map,
)

_SO_RE = re.compile(r"\bSO-\d+\b", re.IGNORECASE)
_QUOTE_RE = re.compile(r"\bSQ-\d+\b", re.IGNORECASE)
_SENT_STATUSES = {"OPEN", "RELEASED"}
_ACK_STATUSES = {"confirmed", "revised"}
_PAIR_CAP = 500
_LIST_CAP = 50

# Card colours. "partial" is reserved for coverage notes, not card status.
_GOOD = "good"
_WARN = "warn"
_BAD = "bad"
_NEUTRAL = "neutral"


def parse_date(value: Any) -> Optional[date]:
    """Calendar date, or None for blank and Business Central's 0001-01-01."""
    if value is None or value is False:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value if value.year >= 1900 else None
    text = str(value).strip()
    if not text or text.startswith("0001-"):
        return None
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return parsed if parsed.year >= 1900 else None


def shift_year(value: date) -> date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value: float) -> float:
    return round(float(value), 2)


def _in_range(value: Optional[date], start: date, end: date) -> bool:
    return value is not None and start <= value <= end


def _delta_pct(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior is None or prior == 0:
        return None
    return round((current - prior) / abs(prior) * 100, 1)


def _delta_status(pct: Optional[float]) -> str:
    if pct is None:
        return _NEUTRAL
    if pct >= 0:
        return _GOOD
    if pct >= -5:
        return _WARN
    return _BAD


def _days_status(days: Optional[float], late_after: int) -> str:
    if days is None:
        return _NEUTRAL
    if days > late_after:
        return _BAD
    if days > 2:
        return _WARN
    return _GOOD


def _rate_status(pct: Optional[float], good: float, warn: float) -> str:
    if pct is None:
        return _NEUTRAL
    if pct >= good:
        return _GOOD
    if pct >= warn:
        return _WARN
    return _BAD


def _po_key(number: Optional[str]) -> str:
    text = (number or "").upper().strip()
    if "(" in text:
        text = text.split("(", 1)[0].strip()
    return text


def _so_numbers(po: dict, extra: Optional[list[str]] = None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        for match in _SO_RE.finditer(text or ""):
            number = match.group(0).upper()
            if number not in seen:
                seen.add(number)
                found.append(number)

    add(po.get("external_document") or "")
    for line in po.get("lines") or []:
        add(line.get("description") or "")
    for number in extra or []:
        add(str(number))
        cleaned = str(number or "").upper().strip()
        if cleaned and cleaned not in seen and _SO_RE.fullmatch(cleaned):
            seen.add(cleaned)
            found.append(cleaned)
    return found


def _quote_numbers(text: str) -> list[str]:
    return [match.group(0).upper() for match in _QUOTE_RE.finditer(text or "")]


def _coverage(kpi_id: str, section: str, title: str, state: str, detail: str) -> dict:
    return {"id": kpi_id, "section": section, "title": title, "state": state, "detail": detail}


def _sum_between(rows: list[dict], start: date, end: date, date_key: str = "posting_date",
                 amount_key: str = "amount") -> float:
    total = 0.0
    for row in rows:
        if _in_range(parse_date(row.get(date_key)), start, end):
            total += _num(row.get(amount_key))
    return _money(total)


def _comparison(amount: float, prior: float, year_ago: float) -> dict:
    return {
        "amount": amount,
        "prior_amount": prior,
        "year_ago_amount": year_ago,
        "prior_delta_pct": _delta_pct(amount, prior),
        "year_ago_delta_pct": _delta_pct(amount, year_ago),
        "status": _delta_status(_delta_pct(amount, prior)),
    }


def _item_index(items: list[dict]) -> dict[str, dict]:
    return {(item.get("number") or "").upper(): item for item in items if item.get("number")}


def _line_category(line: dict, items: dict[str, dict]) -> str:
    item = items.get((line.get("item_number") or "").upper()) or {}
    return item.get("category") or ""


def _unit_cost(line: dict, items: dict[str, dict]) -> Optional[float]:
    item = items.get((line.get("item_number") or "").upper())
    if not item or item.get("unit_cost") is None:
        return None
    return _num(item.get("unit_cost"))


def _sent_info(po: dict, portal: Optional[dict]) -> tuple[Optional[date], Optional[str], bool]:
    """Return (sent date, source, sent?). Portal email time wins over the BC order date."""
    if portal and parse_date(portal.get("emailed_at")):
        return parse_date(portal.get("emailed_at")), "portal_email", True
    status = (po.get("status") or "").upper()
    if status in _SENT_STATUSES and parse_date(po.get("order_date")):
        return parse_date(po.get("order_date")), "bc_order_date", True
    return None, None, False


def _fully_received(po: dict) -> bool:
    item_lines = [
        line for line in (po.get("lines") or [])
        if (line.get("line_type") or "") == "Item" and _num(line.get("quantity")) > 0
    ]
    if not item_lines:
        return False
    return all(
        _num(line.get("received_quantity")) >= _num(line.get("quantity")) - 1e-6
        for line in item_lines
    )


def _required_receipt(po: dict) -> Optional[date]:
    header = parse_date(po.get("requested_receipt_date"))
    if header:
        return header
    expected = [parse_date(line.get("expected_receipt_date")) for line in po.get("lines") or []]
    expected = [value for value in expected if value]
    return max(expected) if expected else None


def _active_acks(acks: list[dict]) -> dict[str, dict]:
    """Earliest confirmation per purchase order. Cancelled rows do not count."""
    chosen: dict[str, dict] = {}
    for ack in acks:
        if (ack.get("status") or "").lower() not in _ACK_STATUSES:
            continue
        key = _po_key(ack.get("po_number"))
        received = parse_date(ack.get("received_at"))
        if not key or received is None:
            continue
        current = chosen.get(key)
        if current is None or received < current["received"]:
            chosen[key] = {"received": received, "ack": ack}
    return chosen


def _purchasing(bundle: dict, start: date, end: date, today: date, product_map: ProductMap,
                errors: dict) -> tuple[dict, list[dict]]:
    late_after = product_map.so_to_po_late_days
    orders = {row["number"].upper(): row for row in bundle.get("sales_orders") or [] if row.get("number")}
    portal_by_po: dict[str, dict] = {}
    for row in bundle.get("po_sends") or []:
        key = _po_key(row.get("po_number"))
        if key:
            portal_by_po[key] = row

    pos_by_key: dict[str, dict] = {}
    for po in bundle.get("purchase_orders") or []:
        key = _po_key(po.get("number"))
        if key:
            pos_by_key[key] = po
    for key, portal in portal_by_po.items():
        pos_by_key.setdefault(key, {
            "number": portal.get("po_number") or key,
            "status": "",
            "order_date": None,
            "requested_receipt_date": None,
            "vendor_number": portal.get("vendor_number"),
            "vendor_name": portal.get("vendor_name"),
            "amount": None,
            "external_document": "",
            "lines": [],
        })

    acks = _active_acks(bundle.get("acks") or [])
    pairs = []
    linked_sos: set[str] = set()
    missing_so_date = 0

    for key, po in pos_by_key.items():
        portal = portal_by_po.get(key)
        so_numbers = _so_numbers(po, (portal or {}).get("so_numbers"))
        sent_date, sent_source, sent = _sent_info(po, portal)
        vendor_name = po.get("vendor_name") or (portal or {}).get("vendor_name") or ""
        vendor_number = po.get("vendor_number") or (portal or {}).get("vendor_number") or ""
        for so_number in so_numbers:
            order = orders.get(so_number)
            order_date = parse_date((order or {}).get("order_date"))
            if order is None or order_date is None:
                missing_so_date += 1
                continue
            if not _in_range(order_date, start, end):
                continue
            linked_sos.add(so_number)
            if sent and sent_date:
                days = (sent_date - order_date).days
                age_days = days
            else:
                days = None
                age_days = (today - order_date).days
            highlight = (days is not None and days > late_after) or (days is None and age_days > late_after)
            pairs.append({
                "sales_order": so_number,
                "sales_order_date": order_date.isoformat(),
                "customer": (order or {}).get("customer_name") or "",
                "purchase_order": po.get("number") or key,
                "vendor_name": vendor_name,
                "vendor_number": vendor_number,
                "po_sent_date": sent_date.isoformat() if sent_date else None,
                "sent_source": sent_source,
                "days": days,
                "age_days": age_days,
                "sent": sent,
                "highlight": highlight,
                "status": _BAD if highlight else (_days_status(days if days is not None else age_days, late_after)),
            })

    pairs.sort(key=lambda row: (not row["highlight"], row["sales_order"], row["purchase_order"]))
    truncated = len(pairs) > _PAIR_CAP
    sent_days = [row["days"] for row in pairs if row["sent"] and row["days"] is not None]
    average = round(sum(sent_days) / len(sent_days), 1) if sent_days else None
    orders_in_range = [
        row for row in orders.values()
        if _in_range(parse_date(row.get("order_date")), start, end)
    ]
    without_po = [
        {
            "sales_order": row.get("number"),
            "sales_order_date": parse_date(row.get("order_date")).isoformat(),
            "customer": row.get("customer_name") or "",
        }
        for row in orders_in_range
        if (row.get("number") or "").upper() not in linked_sos
    ]

    ack_by_vendor: dict[str, list[int]] = defaultdict(list)
    ack_names: dict[str, str] = {}
    for key, po in pos_by_key.items():
        portal = portal_by_po.get(key)
        sent_date, _source, sent = _sent_info(po, portal)
        if not sent or sent_date is None or not _in_range(sent_date, start, end):
            continue
        ack = acks.get(key)
        if not ack:
            continue
        vendor_number = po.get("vendor_number") or (portal or {}).get("vendor_number") or "unknown"
        vendor_name = po.get("vendor_name") or (portal or {}).get("vendor_name") or vendor_number
        ack_by_vendor[vendor_number].append((ack["received"] - sent_date).days)
        ack_names[vendor_number] = vendor_name
    ack_vendors = []
    for vendor_number, days in sorted(ack_by_vendor.items(), key=lambda item: item[0]):
        avg = round(sum(days) / len(days), 1)
        ack_vendors.append({
            "vendor_number": vendor_number,
            "vendor_name": ack_names.get(vendor_number) or vendor_number,
            "average_days": avg,
            "count": len(days),
            "status": _days_status(avg, late_after),
        })
    ack_all = [day for days in ack_by_vendor.values() for day in days]
    ack_average = round(sum(ack_all) / len(ack_all), 1) if ack_all else None

    unacked_vendors: dict[str, dict] = {}
    for key, po in pos_by_key.items():
        portal = portal_by_po.get(key)
        sent_date, _source, sent = _sent_info(po, portal)
        if not sent or sent_date is None or key in acks or _fully_received(po):
            continue
        vendor_number = po.get("vendor_number") or (portal or {}).get("vendor_number") or "unknown"
        vendor_name = po.get("vendor_name") or (portal or {}).get("vendor_name") or vendor_number
        age = (today - sent_date).days
        bucket = unacked_vendors.setdefault(vendor_number, {
            "vendor_number": vendor_number,
            "vendor_name": vendor_name,
            "purchase_orders": [],
        })
        bucket["purchase_orders"].append({
            "number": po.get("number") or key,
            "sent_date": sent_date.isoformat(),
            "age_days": age,
            "amount": _money(_num(po.get("amount"))) if po.get("amount") is not None else None,
            "status": _BAD if age > 7 else (_WARN if age > 3 else _GOOD),
        })
    unacked_list = []
    for bucket in unacked_vendors.values():
        bucket["purchase_orders"].sort(key=lambda row: -row["age_days"])
        ages = [row["age_days"] for row in bucket["purchase_orders"]]
        oldest = max(ages) if ages else 0
        bucket["count"] = len(bucket["purchase_orders"])
        bucket["oldest_days"] = oldest
        bucket["status"] = _BAD if oldest > 7 or bucket["count"] > 5 else (_WARN if oldest > 3 else _GOOD)
        unacked_list.append(bucket)
    unacked_list.sort(key=lambda row: (-row["oldest_days"], row["vendor_name"]))
    unacked_count = sum(row["count"] for row in unacked_list)

    receipts_by_po: dict[str, list[dict]] = defaultdict(list)
    for receipt in bundle.get("receipts") or []:
        posted = parse_date(receipt.get("posting_date"))
        key = _po_key(receipt.get("order_number"))
        if key and _in_range(posted, start, end):
            receipts_by_po[key].append(receipt)
    on_time = late = unknown = 0
    on_time_vendors: dict[str, dict] = {}
    for key, receipts in receipts_by_po.items():
        po = pos_by_key.get(key)
        required = _required_receipt(po) if po else None
        first = min(parse_date(row.get("posting_date")) for row in receipts)
        vendor_number = (po or {}).get("vendor_number") or receipts[0].get("vendor_number") or "unknown"
        vendor_name = (po or {}).get("vendor_name") or receipts[0].get("vendor_name") or vendor_number
        slot = on_time_vendors.setdefault(vendor_number, {
            "vendor_number": vendor_number,
            "vendor_name": vendor_name,
            "on_time": 0,
            "late": 0,
            "unknown": 0,
        })
        if required is None or first is None:
            unknown += 1
            slot["unknown"] += 1
            continue
        if first <= required:
            on_time += 1
            slot["on_time"] += 1
        else:
            late += 1
            slot["late"] += 1
    judged = on_time + late
    rate = round(on_time / judged * 100, 1) if judged else None
    vendor_rates = []
    for slot in on_time_vendors.values():
        judged_vendor = slot["on_time"] + slot["late"]
        vendor_rate = round(slot["on_time"] / judged_vendor * 100, 1) if judged_vendor else None
        slot["rate_pct"] = vendor_rate
        slot["status"] = _rate_status(vendor_rate, 95, 85)
        vendor_rates.append(slot)
    vendor_rates.sort(key=lambda row: ((row["rate_pct"] is None), row["rate_pct"] or 0, row["vendor_name"]))

    blocked = "purchase_orders" in errors or "sales_orders" in errors
    so_state = "missing" if blocked else "partial"
    ack_state = "missing" if "purchase_orders" in errors else "partial"
    on_time_state = "missing" if "purchase_receipts" in errors or "purchase_orders" in errors else "partial"

    coverage = [
        _coverage(
            "so_to_po", "purchasing", "SO to PO sent", so_state,
            "Days run from the sales order date to the day the purchase order was sent. "
            "When the portal recorded the email to the vendor, that time is the sent date. "
            "Otherwise the sent date is the purchase order date in Business Central, and only "
            "after the order is open (a draft has not been sent). Sales orders that are fully "
            "shipped, and purchase orders that are fully received, leave Business Central's "
            "open lists, so older completed pairs are missing unless the portal still has the link.",
        ),
        _coverage(
            "po_ack", "purchasing", "PO sent to vendor acknowledgement", ack_state,
            "Business Central does not store the date a vendor acknowledged a purchase order. "
            "A promised or expected receipt date is a delivery promise, not an acknowledgement, "
            "so it is not used here. Acknowledgement dates come from the portal's Upwardor "
            "acknowledgement inbox. Vendors who confirm outside that inbox have no acknowledgement time.",
        ),
        _coverage(
            "unacknowledged", "purchasing", "Unacknowledged POs", ack_state,
            "This list is every purchase order that has been sent and is not fully received, "
            "and that has no Upwardor acknowledgement on file. It is the open list as of today, "
            "not limited to the date range, so an old unconfirmed order stays visible. "
            "A vendor who confirms by phone or by an email the inbox does not read will still show here. "
            "Draft purchase orders are left out.",
        ),
        _coverage(
            "vendor_ontime", "purchasing", "Vendor on-time rate", on_time_state,
            "On time means the first purchase receipt in the date range was posted on or before "
            "the required receipt date on the purchase order. That required date is still on the "
            "purchase order only while the order is open in Business Central. After the order is "
            "fully posted it drops off that list, and the receipt itself does not include the "
            "required date, so those older orders are not in the percentage.",
        ),
    ]
    section = {
        "so_to_po": {
            "average_days": None if blocked else average,
            "pair_count": 0 if blocked else len(pairs),
            "sent_count": 0 if blocked else len(sent_days),
            "unsent_count": 0 if blocked else sum(1 for row in pairs if not row["sent"]),
            "late_count": 0 if blocked else sum(1 for row in pairs if row["highlight"]),
            "status": _NEUTRAL if blocked else _days_status(average, late_after),
            "sales_orders_without_po": 0 if blocked else len(without_po),
            "orders_without_purchase_order": [] if blocked else without_po[:_LIST_CAP],
            "pairs_missing_order_date": missing_so_date,
            "truncated": truncated,
            "pairs": [] if blocked else pairs[:_PAIR_CAP],
        },
        "acknowledgements": {
            "average_days": None if "purchase_orders" in errors else ack_average,
            "vendors": [] if "purchase_orders" in errors else ack_vendors,
            "status": _NEUTRAL if "purchase_orders" in errors else _days_status(ack_average, late_after),
        },
        "unacknowledged": {
            "count": None if "purchase_orders" in errors else unacked_count,
            "status": _NEUTRAL if "purchase_orders" in errors else (
                _GOOD if unacked_count == 0 else (_BAD if unacked_count > 5 else _WARN)
            ),
            "as_of": today.isoformat(),
            "vendors": [] if "purchase_orders" in errors else unacked_list,
        },
        "on_time": {
            "rate_pct": None if on_time_state == "missing" else rate,
            "on_time": 0 if on_time_state == "missing" else on_time,
            "late": 0 if on_time_state == "missing" else late,
            "unknown": 0 if on_time_state == "missing" else unknown,
            "status": _NEUTRAL if on_time_state == "missing" else _rate_status(rate, 95, 85),
            "vendors": [] if on_time_state == "missing" else vendor_rates,
        },
    }
    return section, coverage


def _period_bounds(start: date, end: date) -> dict[str, date]:
    length = (end - start).days
    prior_end = start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=length)
    week_start = end - timedelta(days=end.weekday())
    week_end = min(end, week_start + timedelta(days=6))
    prev_week_end = week_start - timedelta(days=1)
    prev_week_start = prev_week_end - timedelta(days=6)
    month_start = end.replace(day=1)
    previous_month_end = month_start - timedelta(days=1)
    elapsed = (end - month_start).days
    prev_month_start = previous_month_end.replace(day=1)
    prev_month_end = min(previous_month_end, prev_month_start + timedelta(days=elapsed))
    return {
        "prior_start": prior_start,
        "prior_end": prior_end,
        "year_start": shift_year(start),
        "year_end": shift_year(end),
        "week_start": week_start,
        "week_end": week_end,
        "prev_week_start": prev_week_start,
        "prev_week_end": prev_week_end,
        "week_year_start": shift_year(week_start),
        "week_year_end": shift_year(week_end),
        "month_start": month_start,
        "month_end": end,
        "prev_month_start": prev_month_start,
        "prev_month_end": prev_month_end,
        "month_year_start": shift_year(month_start),
        "month_year_end": shift_year(end),
    }


def _invoice_lines(invoice: dict) -> list[dict]:
    return [line for line in (invoice.get("lines") or []) if (line.get("line_type") or "Item") != "Comment"]


def _sales(bundle: dict, start: date, end: date, product_map: ProductMap, errors: dict) -> tuple[dict, list[dict]]:
    invoices = bundle.get("invoices") or []
    missing = "sales_invoices" in errors
    bounds = _period_bounds(start, end)
    items = _item_index(bundle.get("items") or [])

    def total(window_start: date, window_end: date) -> float:
        return _sum_between(invoices, window_start, window_end)

    range_total = _comparison(
        total(start, end),
        total(bounds["prior_start"], bounds["prior_end"]),
        total(bounds["year_start"], bounds["year_end"]),
    )
    week = _comparison(
        total(bounds["week_start"], bounds["week_end"]),
        total(bounds["prev_week_start"], bounds["prev_week_end"]),
        total(bounds["week_year_start"], bounds["week_year_end"]),
    )
    week["label"] = f"Week of {bounds['week_start'].strftime('%b')} {bounds['week_start'].day}"
    week["from"] = bounds["week_start"].isoformat()
    week["to"] = bounds["week_end"].isoformat()
    month = _comparison(
        total(bounds["month_start"], bounds["month_end"]),
        total(bounds["prev_month_start"], bounds["prev_month_end"]),
        total(bounds["month_year_start"], bounds["month_year_end"]),
    )
    month["label"] = bounds["month_start"].strftime("%B %Y")
    month["from"] = bounds["month_start"].isoformat()
    month["to"] = bounds["month_end"].isoformat()

    weekly_series = []
    cursor = start - timedelta(days=start.weekday())
    while cursor <= end:
        week_end = cursor + timedelta(days=6)
        clip_start = max(cursor, start)
        clip_end = min(week_end, end)
        weekly_series.append({
            "week_start": cursor.isoformat(),
            "label": f"{cursor.strftime('%b')} {cursor.day}",
            "amount": total(clip_start, clip_end),
            "year_ago_amount": total(shift_year(clip_start), shift_year(clip_end)),
        })
        cursor += timedelta(days=7)

    monthly_series = []
    month_cursor = start.replace(day=1)
    while month_cursor <= end:
        if month_cursor.month == 12:
            month_end = date(month_cursor.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(month_cursor.year, month_cursor.month + 1, 1) - timedelta(days=1)
        clip_start = max(month_cursor, start)
        clip_end = min(month_end, end)
        monthly_series.append({
            "month": month_cursor.strftime("%Y-%m"),
            "label": month_cursor.strftime("%b %Y"),
            "amount": total(clip_start, clip_end),
            "year_ago_amount": total(shift_year(clip_start), shift_year(clip_end)),
        })
        month_cursor = month_end + timedelta(days=1)

    mix_current: dict[str, float] = defaultdict(float)
    mix_prior: dict[str, float] = defaultdict(float)
    item_current: dict[tuple, float] = defaultdict(float)
    item_prior: dict[tuple, float] = defaultdict(float)
    item_desc: dict[tuple, str] = {}
    operator_current: dict[str, float] = defaultdict(float)
    operator_prior: dict[str, float] = defaultdict(float)
    freight_current = 0.0

    def accumulate(invoice: dict, into_mix: dict, into_items: dict, into_ops: dict, count_freight: bool) -> None:
        nonlocal freight_current
        for line in _invoice_lines(invoice):
            amount = _num(line.get("amount"))
            description = line.get("description") or ""
            item_number = line.get("item_number") or ""
            if is_freight(product_map, item_number, description):
                if count_freight:
                    freight_current += amount
                continue
            operator = classify_operator(product_map, item_number, description)
            if operator:
                into_ops[operator.id] += amount
            group = classify_product_line(
                product_map, item_number, description, _line_category(line, items),
            )
            if group is None and operator:
                continue
            group_id = group.id if group else "other"
            into_mix[group_id] += amount
            if item_number or description:
                key = (group_id, item_number or description)
                into_items[key] += amount
                item_desc.setdefault(key, description)

    for invoice in invoices:
        posted = parse_date(invoice.get("posting_date"))
        if _in_range(posted, start, end):
            accumulate(invoice, mix_current, item_current, operator_current, True)
        elif _in_range(posted, bounds["prior_start"], bounds["prior_end"]):
            accumulate(invoice, mix_prior, item_prior, operator_prior, False)

    mix_total = sum(mix_current.values())
    line_rows = []
    for group in product_map.lines:
        amount = _money(mix_current.get(group.id, 0))
        prior_amount = _money(mix_prior.get(group.id, 0))
        line_rows.append({
            "id": group.id,
            "label": group.label,
            "amount": amount,
            "prior_amount": prior_amount,
            "share_pct": round(amount / mix_total * 100, 1) if mix_total else 0,
            "status": _NEUTRAL,
        })
    other_amount = _money(mix_current.get("other", 0))
    if mix_total:
        # shares were based on mix including other; recompute against doors + other
        pass
    top_movers = {}
    for group in list(product_map.lines) + [type("G", (), {"id": "other"})()]:
        ranked = []
        keys = {key for key in item_current if key[0] == group.id} | {key for key in item_prior if key[0] == group.id}
        for key in keys:
            current_amount = _money(item_current.get(key, 0))
            prior_amount = _money(item_prior.get(key, 0))
            ranked.append({
                "item_number": key[1] if key[1] != item_desc.get(key) else key[1],
                "description": item_desc.get(key) or "",
                "amount": current_amount,
                "prior_amount": prior_amount,
                "delta": _money(current_amount - prior_amount),
            })
        ranked.sort(key=lambda row: abs(row["delta"]), reverse=True)
        top_movers[group.id] = [row for row in ranked if row["amount"] or row["prior_amount"]][:5]

    brands = []
    for group in product_map.operators:
        amount = _money(operator_current.get(group.id, 0))
        prior_amount = _money(operator_prior.get(group.id, 0))
        brands.append({
            "id": group.id,
            "label": group.label,
            "amount": amount,
            "prior_amount": prior_amount,
            "delta_pct": _delta_pct(amount, prior_amount),
            "status": _delta_status(_delta_pct(amount, prior_amount)) if prior_amount else _NEUTRAL,
        })

    quotes = bundle.get("quotes") or []
    open_numbers = {(row.get("number") or "").upper() for row in quotes if row.get("number")}
    period_open = {
        (row.get("number") or "").upper()
        for row in quotes
        if row.get("number") and _in_range(parse_date(row.get("document_date")), start, end)
    }
    converted: set[str] = set()
    for order in bundle.get("sales_orders") or []:
        if not _in_range(parse_date(order.get("order_date")), start, end):
            continue
        for number in _quote_numbers(order.get("external_document") or ""):
            if number not in open_numbers:
                converted.add(number)
    open_value = _money(sum(_num(row.get("amount")) for row in quotes))
    denom = len(converted) + len(period_open)
    conversion = round(len(converted) / denom * 100, 1) if denom else None

    if missing:
        range_total = _comparison(0, 0, 0)
        for block in (range_total, week, month):
            block["amount"] = None
            block["prior_amount"] = None
            block["year_ago_amount"] = None
            block["prior_delta_pct"] = None
            block["year_ago_delta_pct"] = None
            block["status"] = _NEUTRAL
        weekly_series = []
        monthly_series = []
        line_rows = []
        other_amount = None
        top_movers = {}
        brands = []
        freight_current = 0

    sales_state = "missing" if missing else "ok"
    mix_state = "missing" if missing else "partial"
    quote_state = "missing" if "sales_quotes" in errors and "sales_orders" in errors else "partial"
    coverage = [
        _coverage(
            "sales", "sales", "Weekly and monthly sales", sales_state,
            "Sales are posted sales invoices, before tax, by the invoice posting date. "
            "Each figure is compared with the period just before it and with the same dates last year.",
        ),
        _coverage(
            "product_mix", "sales", "Product mix", mix_state,
            "Invoice lines are grouped by item number, description, and item category. "
            "TX450 and Thermalex are commercial. Kanata, Craft, and anything marked residential "
            "are residential. AL976 and aluminum are aluminum. The default list also includes the "
            "other commercial series in the catalog (TX380, TX500, TX760) and the other aluminum "
            "names (SWD, Panorama, Solalite). Lines that match none of these are Other. "
            "The list is a file the office can change without a code change.",
        ),
        _coverage(
            "operators", "sales", "Operator sales by brand", mix_state,
            "Operator sales are invoice lines whose item number or description names LiftMaster, "
            "Micanan or McKinnon, or Guardian. Lines that do not name one of those brands are not included.",
        ),
        _coverage(
            "quotes", "sales", "Quote conversion", quote_state,
            "Business Central only keeps quotes that are still open. Once a quote becomes an order, "
            "the quote usually disappears, and a fully shipped order disappears too. Conversion counts "
            "an order in this date range only when its external document number is a quote number that "
            "is no longer open. Open quote value is every quote still open in Business Central, before tax, "
            "and is not limited to the date range.",
        ),
    ]
    section = {
        "range_total": range_total,
        "week": week,
        "month": month,
        "weekly_series": weekly_series,
        "monthly_series": monthly_series,
        "product_mix": {
            "lines": line_rows,
            "other_amount": None if missing else other_amount,
            "unmapped_share_pct": None if missing or not mix_total else round(other_amount / mix_total * 100, 1),
            "top_movers": top_movers,
        },
        "operators": {
            "brands": brands,
            "total": None if missing else _money(sum(row["amount"] for row in brands)),
        },
        "quotes": {
            "conversion_pct": None if "sales_quotes" in errors and "sales_orders" in errors else conversion,
            "converted_count": len(converted),
            "open_in_period": len(period_open),
            "open_quote_value": None if "sales_quotes" in errors else open_value,
            "open_quote_count": 0 if "sales_quotes" in errors else len(quotes),
            "status": _NEUTRAL if conversion is None else _rate_status(conversion, 40, 20),
        },
        "freight_from_lines": _money(freight_current),
    }
    return section, coverage


def _margin_for_lines(lines: list[dict], product_map: ProductMap, items: dict[str, dict]) -> dict:
    sales = 0.0
    cost = 0.0
    incomplete = False
    by_line: dict[str, dict] = defaultdict(lambda: {"sales": 0.0, "cost": 0.0, "incomplete": False})
    for line in lines:
        if (line.get("line_type") or "Item") == "Comment":
            continue
        description = line.get("description") or ""
        item_number = line.get("item_number") or ""
        if is_freight(product_map, item_number, description):
            continue
        amount = _num(line.get("amount"))
        sales += amount
        group = classify_product_line(product_map, item_number, description, _line_category(line, items))
        group_id = group.id if group else "other"
        by_line[group_id]["sales"] += amount
        if (line.get("line_type") or "Item") != "Item" or not item_number:
            continue
        unit = _unit_cost(line, items)
        if unit is None:
            incomplete = True
            by_line[group_id]["incomplete"] = True
            continue
        line_cost = unit * _num(line.get("quantity"))
        cost += line_cost
        by_line[group_id]["cost"] += line_cost
    margin = sales - cost
    pct = round(margin / sales * 100, 1) if sales else None
    return {
        "sales": _money(sales),
        "cost": _money(cost),
        "margin": _money(margin),
        "margin_pct": pct,
        "incomplete": incomplete,
        "by_line": by_line,
    }


def _financial(bundle: dict, start: date, end: date, today: date, product_map: ProductMap,
               sales_section: dict, errors: dict) -> tuple[dict, list[dict]]:
    items = _item_index(bundle.get("items") or [])
    threshold = product_map.low_margin_pct
    invoice_error = "sales_invoices" in errors
    combined = defaultdict(lambda: {"sales": 0.0, "cost": 0.0, "incomplete": False})
    low_orders = []
    incomplete_orders = 0
    total_sales = total_cost = 0.0
    if not invoice_error:
        for invoice in bundle.get("invoices") or []:
            if not _in_range(parse_date(invoice.get("posting_date")), start, end):
                continue
            scored = _margin_for_lines(_invoice_lines(invoice), product_map, items)
            if scored["sales"] <= 0 and scored["cost"] <= 0:
                continue
            total_sales += scored["sales"]
            total_cost += scored["cost"]
            if scored["incomplete"]:
                incomplete_orders += 1
            for group_id, bucket in scored["by_line"].items():
                combined[group_id]["sales"] += bucket["sales"]
                combined[group_id]["cost"] += bucket["cost"]
                combined[group_id]["incomplete"] = combined[group_id]["incomplete"] or bucket["incomplete"]
            if scored["margin_pct"] is not None and scored["margin_pct"] < threshold:
                low_orders.append({
                    "invoice": invoice.get("number"),
                    "customer": invoice.get("customer_name") or "",
                    "sales": scored["sales"],
                    "cost": scored["cost"],
                    "margin_amount": scored["margin"],
                    "margin_pct": scored["margin_pct"],
                    "cost_incomplete": scored["incomplete"],
                    "status": _BAD,
                })
    low_orders.sort(key=lambda row: row["margin_pct"])
    overall_pct = round((total_sales - total_cost) / total_sales * 100, 1) if total_sales else None
    by_line = []
    for group in list(product_map.lines) + [type("G", (), {"id": "other", "label": "Other"})()]:
        bucket = combined.get(group.id) or {"sales": 0.0, "cost": 0.0, "incomplete": False}
        sales_amount = _money(bucket["sales"])
        cost_amount = _money(bucket["cost"])
        pct = round((sales_amount - cost_amount) / sales_amount * 100, 1) if sales_amount else None
        by_line.append({
            "id": group.id,
            "label": getattr(group, "label", "Other"),
            "sales": sales_amount,
            "cost": cost_amount,
            "margin_amount": _money(sales_amount - cost_amount),
            "margin_pct": pct,
            "cost_incomplete": bucket["incomplete"],
            "status": _NEUTRAL if pct is None else (_BAD if pct < threshold else (_WARN if pct < threshold + 5 else _GOOD)),
        })

    pos = {_po_key(po.get("number")): po for po in bundle.get("purchase_orders") or [] if po.get("number")}
    variance_error = "purchase_invoices" in errors
    by_vendor: dict[str, dict] = {}
    compared = missing_po = 0
    variance_total = 0.0
    if not variance_error:
        for invoice in bundle.get("purchase_invoices") or []:
            if not _in_range(parse_date(invoice.get("posting_date")), start, end):
                continue
            if (invoice.get("status") or "").lower() == "draft":
                continue
            vendor_number = invoice.get("vendor_number") or "unknown"
            vendor_name = invoice.get("vendor_name") or vendor_number
            slot = by_vendor.setdefault(vendor_number, {
                "vendor_number": vendor_number,
                "vendor_name": vendor_name,
                "variance_amount": 0.0,
                "invoice_count": 0,
                "missing_po_count": 0,
            })
            slot["invoice_count"] += 1
            po = pos.get(_po_key(invoice.get("order_number")))
            if po is None or po.get("amount") is None:
                slot["missing_po_count"] += 1
                missing_po += 1
                continue
            variance = _num(invoice.get("amount")) - _num(po.get("amount"))
            slot["variance_amount"] += variance
            variance_total += variance
            compared += 1
    vendor_rows = []
    for slot in by_vendor.values():
        amount = _money(slot["variance_amount"])
        slot["variance_amount"] = amount
        slot["status"] = _GOOD if abs(amount) < 25 else (_WARN if abs(amount) < 250 else _BAD)
        vendor_rows.append(slot)
    vendor_rows.sort(key=lambda row: abs(row["variance_amount"]), reverse=True)

    balance_total = _money(sum(_num(row.get("balance")) for row in bundle.get("customers") or [] if _num(row.get("balance")) > 0))
    credit_balances = _money(sum(abs(_num(row.get("balance"))) for row in bundle.get("customers") or [] if _num(row.get("balance")) < 0))
    buckets = [
        ("current", "Current", 0),
        ("1_30", "1–30 days", 0),
        ("31_60", "31–60 days", 0),
        ("61_90", "61–90 days", 0),
        ("over_90", "Over 90 days", 0),
    ]
    amounts = {key: 0.0 for key, _label, _n in buckets}
    ar_error = "open_invoices" in errors
    if not ar_error:
        for invoice in bundle.get("open_invoices") or []:
            if (invoice.get("status") or "Open").lower() not in {"open", ""}:
                continue
            due = parse_date(invoice.get("due_date"))
            days_past = 0 if due is None else (today - due).days
            if days_past <= 0:
                key = "current"
            elif days_past <= 30:
                key = "1_30"
            elif days_past <= 60:
                key = "31_60"
            elif days_past <= 90:
                key = "61_90"
            else:
                key = "over_90"
            amounts[key] += _num(invoice.get("amount"))
    bucket_rows = []
    for key, label, _n in buckets:
        amount = None if ar_error else _money(amounts[key])
        if key == "over_90" and amount:
            status = _BAD
        elif key == "61_90" and amount:
            status = _WARN
        else:
            status = _NEUTRAL
        bucket_rows.append({"id": key, "label": label, "amount": amount, "status": status})
    deposits = bundle.get("deposits") or {"state": "missing", "amount": None, "detail": ""}
    ar_status = _NEUTRAL
    if not ar_error and amounts["over_90"] > 0:
        ar_status = _BAD
    elif not ar_error and amounts["61_90"] > 0:
        ar_status = _WARN

    backlog_amount = 0.0
    backlog_orders = 0
    backlog_error = "sales_orders" in errors
    if not backlog_error:
        for order in bundle.get("sales_orders") or []:
            outstanding = 0.0
            had_line = False
            for line in order.get("lines") or []:
                if (line.get("line_type") or "Item") == "Comment":
                    continue
                qty = _num(line.get("quantity"))
                if qty <= 0:
                    continue
                had_line = True
                remaining = max(qty - _num(line.get("shipped_quantity")), 0)
                outstanding += _num(line.get("amount")) * (remaining / qty)
            if not had_line:
                outstanding = _num(order.get("amount"))
            if outstanding > 0.005:
                backlog_orders += 1
                backlog_amount += outstanding

    margin_status = _NEUTRAL if overall_pct is None else (
        _BAD if overall_pct < threshold else (_WARN if overall_pct < threshold + 5 else _GOOD)
    )
    coverage = [
        _coverage(
            "margin", "financial", "Gross margin",
            "missing" if invoice_error or "items" in errors else "partial",
            "Margin is the invoice line amount before tax, minus quantity times the unit cost "
            "on the item card. Business Central's invoice line does not include the posted cost "
            "of goods, so this is item-card cost, not the exact cost posted to the ledger. "
            "A line with no item cost is left out of the cost and the order is marked incomplete. "
            f"Orders under {threshold:g}% margin are flagged.",
        ),
        _coverage(
            "po_variance", "financial", "Purchase invoice vs PO",
            "missing" if variance_error else "partial",
            "The difference is the posted purchase invoice total minus the purchase order total, "
            "before tax, for invoices in the date range. The purchase order total is available only "
            "while that order is still open in Business Central. Invoices whose purchase order has "
            "already closed are counted, but they have no difference.",
        ),
        _coverage(
            "ar", "financial", "AR aging and deposits",
            "missing" if "customers" in errors and ar_error else "partial",
            "The total owing is the balance on each customer card in Business Central. "
            "The aging buckets are open sales invoices sorted by due date, at the full invoice "
            "amount before tax. The invoice list does not say how much of an invoice is still unpaid, "
            "so a partly paid invoice is aged at its full amount, and the buckets may not add up to "
            "the customer-card total. "
            + (
                deposits.get("detail")
                or "Customer deposits and prepayments are not on the standard invoice or customer list."
            ),
        ),
        _coverage(
            "backlog", "financial", "Open order backlog",
            "missing" if backlog_error else "ok",
            "Backlog is open sales orders, the part not yet shipped, before tax. "
            "Each line contributes its amount times the share of quantity still to ship.",
        ),
    ]
    if invoice_error:
        margin_block = {
            "sales": None, "cost": None, "margin_amount": None, "margin_pct": None,
            "status": _NEUTRAL, "incomplete_orders": 0, "by_line": [], "low_margin_orders": [],
            "threshold_pct": threshold,
        }
    else:
        margin_block = {
            "sales": _money(total_sales),
            "cost": _money(total_cost),
            "margin_amount": _money(total_sales - total_cost),
            "margin_pct": overall_pct,
            "status": margin_status,
            "incomplete_orders": incomplete_orders,
            "by_line": by_line,
            "low_margin_orders": low_orders[:_LIST_CAP],
            "threshold_pct": threshold,
        }
    section = {
        "margin": margin_block,
        "po_variance": {
            "variance_amount": None if variance_error else _money(variance_total),
            "status": _NEUTRAL if variance_error or compared == 0 else (
                _GOOD if abs(variance_total) < 25 else (_WARN if abs(variance_total) < 250 else _BAD)
            ),
            "compared_count": 0 if variance_error else compared,
            "missing_po_count": 0 if variance_error else missing_po,
            "vendors": [] if variance_error else vendor_rows,
        },
        "ar": {
            "total": None if "customers" in errors else balance_total,
            "customer_count": 0 if "customers" in errors else sum(
                1 for row in bundle.get("customers") or [] if _num(row.get("balance")) > 0
            ),
            "buckets": bucket_rows,
            "deposits": {
                "amount": deposits.get("amount"),
                "state": deposits.get("state") or "missing",
                "detail": deposits.get("detail") or "",
            },
            "credit_balances": None if "customers" in errors else credit_balances,
            "status": ar_status,
        },
        "backlog": {
            "amount": None if backlog_error else _money(backlog_amount),
            "order_count": 0 if backlog_error else backlog_orders,
            "status": _NEUTRAL,
        },
    }
    # freight amount was accumulated while classifying sales; keep the hook for operations
    section["_freight_amount"] = sales_section.get("freight_from_lines")
    return section, coverage


def _operations(bundle: dict, start: date, end: date, today: date, product_map: ProductMap,
                freight_amount: Optional[float], sales_amount: Optional[float], errors: dict) -> tuple[dict, list[dict]]:
    ship_error = "sales_shipments" in errors
    orders = {(row.get("number") or "").upper(): row for row in bundle.get("sales_orders") or []}
    days = []
    missing_order_date = 0
    shipment_count = 0
    if not ship_error:
        for shipment in bundle.get("shipments") or []:
            posted = parse_date(shipment.get("posting_date"))
            if not _in_range(posted, start, end):
                continue
            shipment_count += 1
            order_date = parse_date(shipment.get("order_date"))
            if order_date is None:
                order = orders.get((shipment.get("order_number") or "").upper())
                order_date = parse_date((order or {}).get("order_date"))
            if order_date is None or posted is None:
                missing_order_date += 1
                continue
            gap = (posted - order_date).days
            if gap >= 0:
                days.append(gap)
            else:
                missing_order_date += 1
    average = round(sum(days) / len(days), 1) if days else None

    inventory_error = "items" in errors
    value = 0.0
    stocked = []
    if not inventory_error:
        for item in bundle.get("items") or []:
            on_hand = _num(item.get("on_hand"))
            if on_hand <= 0:
                continue
            item_value = on_hand * _num(item.get("unit_cost"))
            value += item_value
            stocked.append({
                "item_number": item.get("number"),
                "description": item.get("description") or "",
                "on_hand": on_hand,
                "value": _money(item_value),
                "reorder_point": item.get("reorder_point"),
            })
    slow_start = parse_date(bundle.get("slow_window_start")) or (today - timedelta(days=product_map.slow_mover_days))
    sold: set[str] = set()
    if "sales_invoices" not in errors:
        for invoice in bundle.get("invoices") or []:
            if not _in_range(parse_date(invoice.get("posting_date")), slow_start, end):
                continue
            for line in _invoice_lines(invoice):
                number = (line.get("item_number") or "").upper()
                if number:
                    sold.add(number)
    slow = [row for row in stocked if (row["item_number"] or "").upper() not in sold]
    slow.sort(key=lambda row: row["value"], reverse=True)
    reorder_state = bundle.get("reorder_state") or "missing"
    below = []
    if reorder_state == "ok":
        for row in stocked:
            point = row.get("reorder_point")
            if point is None:
                continue
            point_num = _num(point)
            if point_num > 0 and row["on_hand"] < point_num:
                below.append({
                    **row,
                    "reorder_point": point_num,
                    "shortfall": round(point_num - row["on_hand"], 2),
                })
        below.sort(key=lambda row: row["shortfall"], reverse=True)

    freight_pct = None
    if freight_amount is not None and sales_amount:
        freight_pct = round(freight_amount / sales_amount * 100, 1)
    freight_status = _NEUTRAL if freight_pct is None else (_GOOD if freight_pct <= 4 else (_WARN if freight_pct <= 8 else _BAD))
    reorder_note = (
        "Reorder point is read from the Items web service."
        if reorder_state == "ok"
        else "Reorder point is not on the standard item list. The Items web service did not "
             "include Reorder Point, so items below reorder point are unavailable."
    )
    coverage = [
        _coverage(
            "order_to_ship", "operations", "Order to ship",
            "missing" if ship_error else "partial",
            "Days run from the sales order date to the shipment posting date. "
            "The shipment record in Business Central does not include the original order date "
            "unless that field is filled in. When it is blank, the date is taken from the sales "
            "order while that order is still open. Shipments whose order has already closed are left out.",
        ),
        _coverage(
            "inventory", "operations", "Inventory",
            "missing" if inventory_error else ("partial" if reorder_state != "ok" else "ok"),
            "Inventory value is quantity on hand times the item's unit cost. "
            f"Slow movers are items still in stock with no sales invoice since {slow_start.isoformat()} "
            "(the date range, extended to at least "
            f"{product_map.slow_mover_days} days). " + reorder_note,
        ),
        _coverage(
            "freight", "operations", "Freight cost as % of sales",
            "missing" if "sales_invoices" in errors else "partial",
            "Freight is invoice lines whose item number or description matches the freight words "
            "in the product-line file (freight, shipping charge, delivery charge). "
            "Freight posted only to a general-ledger account with a different description is not included. "
            "The percentage is that freight total divided by sales before tax in the date range.",
        ),
    ]
    inventory_status = _NEUTRAL
    if reorder_state == "ok":
        inventory_status = _GOOD if not below else (_WARN if len(below) <= 10 else _BAD)
    section = {
        "order_to_ship": {
            "average_days": None if ship_error else average,
            "shipment_count": 0 if ship_error else shipment_count,
            "with_order_date": 0 if ship_error else len(days),
            "missing_order_date": 0 if ship_error else missing_order_date,
            "status": _NEUTRAL if ship_error else _days_status(average, 14),
        },
        "inventory": {
            "value": None if inventory_error else _money(value),
            "item_count": 0 if inventory_error else len(stocked),
            "slow_movers": [] if inventory_error else slow[:_LIST_CAP],
            "slow_count": 0 if inventory_error else len(slow),
            "slow_since": slow_start.isoformat(),
            "below_reorder": below[:_LIST_CAP],
            "below_reorder_count": len(below),
            "reorder_state": "missing" if inventory_error else reorder_state,
            "status": inventory_status,
        },
        "freight": {
            "amount": None if "sales_invoices" in errors else freight_amount,
            "sales": None if "sales_invoices" in errors else sales_amount,
            "percent": None if "sales_invoices" in errors else freight_pct,
            "status": _NEUTRAL if "sales_invoices" in errors else freight_status,
        },
    }
    return section, coverage


def build_kpi_dashboard(bundle: dict, start: date, end: date, today: Optional[date] = None,
                        product_map: Optional[ProductMap] = None) -> dict:
    today = today or date.today()
    product_map = product_map or load_product_map()
    errors = dict(bundle.get("errors") or {})
    purchasing, purchasing_notes = _purchasing(bundle, start, end, today, product_map, errors)
    sales, sales_notes = _sales(bundle, start, end, product_map, errors)
    financial, financial_notes = _financial(bundle, start, end, today, product_map, sales, errors)
    freight_amount = None if "sales_invoices" in errors else sales.get("freight_from_lines")
    sales_amount = None if "sales_invoices" in errors else (sales.get("range_total") or {}).get("amount")
    operations, operations_notes = _operations(
        bundle, start, end, today, product_map, freight_amount, sales_amount, errors,
    )
    sales.pop("freight_from_lines", None)
    financial.pop("_freight_amount", None)
    length = (end - start).days
    prior_end = start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=length)
    public_map = product_map.public()
    return {
        "range": {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "days": length + 1,
            "prior_from": prior_start.isoformat(),
            "prior_to": prior_end.isoformat(),
            "year_ago_from": shift_year(start).isoformat(),
            "year_ago_to": shift_year(end).isoformat(),
        },
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "product_lines": public_map["lines"],
        "operators": public_map["operators"],
        "thresholds": {
            "so_to_po_late_days": product_map.so_to_po_late_days,
            "low_margin_pct": product_map.low_margin_pct,
            "on_time_good_pct": 95,
            "on_time_warn_pct": 85,
            "quote_conversion_good_pct": 40,
            "quote_conversion_warn_pct": 20,
            "freight_good_pct": 4,
            "freight_warn_pct": 8,
            "order_to_ship_late_days": 14,
        },
        "sources": {
            name: ("error" if name in errors else "ok")
            for name in (
                "sales_orders", "sales_invoices", "sales_quotes", "sales_shipments",
                "purchase_orders", "purchase_invoices", "purchase_receipts",
                "items", "customers", "open_invoices",
            )
        },
        "source_errors": errors,
        "coverage": purchasing_notes + sales_notes + financial_notes + operations_notes,
        "sections": {
            "purchasing": purchasing,
            "sales": sales,
            "financial": financial,
            "operations": operations,
        },
    }


def empty_bundle() -> dict:
    return {
        "sales_orders": [],
        "purchase_orders": [],
        "po_sends": [],
        "acks": [],
        "receipts": [],
        "invoices": [],
        "open_invoices": [],
        "quotes": [],
        "shipments": [],
        "items": [],
        "customers": [],
        "purchase_invoices": [],
        "deposits": {"state": "missing", "amount": None, "detail": ""},
        "reorder_state": "missing",
        "slow_window_start": None,
        "errors": {},
    }
