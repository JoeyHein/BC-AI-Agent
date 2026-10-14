"""Document-level trace for a KPI month, and the text report that prints it.

The staff page does not use this. The validation script does, so a month's
figures can be checked against Business Central document by document.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from app.services.kpi_compute import _in_range, parse_date


def _docs(rows: list[dict], start: date, end: date, date_key: str, fields: tuple[str, ...]) -> list[dict]:
    picked = []
    for row in rows or []:
        if not _in_range(parse_date(row.get(date_key)), start, end):
            continue
        picked.append({key: row.get(key) for key in fields})
    picked.sort(key=lambda row: (str(row.get(date_key) or ""), str(row.get("number") or "")))
    return picked


def collect_trace(bundle: dict, start: date, end: date, payload: Optional[dict] = None) -> dict:
    """Numbers and counts behind each KPI. Dates outside the month are left out."""
    payload = payload or {}
    sections = payload.get("sections") or {}
    purchasing = sections.get("purchasing") or {}
    sales = sections.get("sales") or {}
    financial = sections.get("financial") or {}
    operations = sections.get("operations") or {}
    month = sales.get("month") or {}
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "comparisons": {
            "prior_month": {"from": month.get("prior_from"), "to": month.get("prior_to")},
            "same_month_last_year": {"from": month.get("year_ago_from"), "to": month.get("year_ago_to")},
        },
        "kpis": {
            "so_to_po_days": (purchasing.get("so_to_po") or {}).get("average_days"),
            "so_to_po_late_count": (purchasing.get("so_to_po") or {}).get("late_count"),
            "ack_days": (purchasing.get("acknowledgements") or {}).get("average_days"),
            "unacknowledged_count": (purchasing.get("unacknowledged") or {}).get("count"),
            "on_time_pct": (purchasing.get("on_time") or {}).get("rate_pct"),
            "sales": (sales.get("range_total") or {}).get("amount"),
            "sales_prior_month": month.get("prior_amount"),
            "sales_prior_month_delta_pct": month.get("prior_delta_pct"),
            "sales_last_year": month.get("year_ago_amount"),
            "sales_last_year_delta_pct": month.get("year_ago_delta_pct"),
            "quote_conversion_pct": (sales.get("quotes") or {}).get("conversion_pct"),
            "open_quote_value": (sales.get("quotes") or {}).get("open_quote_value"),
            "margin_pct": (financial.get("margin") or {}).get("margin_pct"),
            "po_variance": (financial.get("po_variance") or {}).get("variance_amount"),
            "ar_total": (financial.get("ar") or {}).get("total"),
            "backlog": (financial.get("backlog") or {}).get("amount"),
            "order_to_ship_days": (operations.get("order_to_ship") or {}).get("average_days"),
            "inventory_value": (operations.get("inventory") or {}).get("value"),
            "below_reorder_count": (operations.get("inventory") or {}).get("below_reorder_count"),
            "freight_pct": (operations.get("freight") or {}).get("percent"),
        },
        "sales_invoices": _docs(
            bundle.get("invoices") or [], start, end, "posting_date",
            ("number", "posting_date", "amount", "customer_name"),
        ),
        "sales_orders": _docs(
            bundle.get("sales_orders") or [], start, end, "order_date",
            ("number", "order_date", "amount", "customer_name"),
        ),
        "so_po_pairs": [
            {
                "sales_order": row.get("sales_order"),
                "purchase_order": row.get("purchase_order"),
                "vendor_name": row.get("vendor_name"),
                "days": row.get("days"),
                "po_sent_date": row.get("po_sent_date"),
            }
            for row in (purchasing.get("so_to_po") or {}).get("pairs") or []
        ],
        "acknowledgements": [
            {
                "vendor_name": row.get("vendor_name"),
                "average_days": row.get("average_days"),
                "count": row.get("count"),
            }
            for row in (purchasing.get("acknowledgements") or {}).get("vendors") or []
        ],
        "unacknowledged_purchase_orders": [
            {
                "vendor_name": vendor.get("vendor_name"),
                "number": po.get("number"),
                "sent_date": po.get("sent_date"),
                "age_days": po.get("age_days"),
                "amount": po.get("amount"),
            }
            for vendor in (purchasing.get("unacknowledged") or {}).get("vendors") or []
            for po in vendor.get("purchase_orders") or []
        ],
        "receipts": _docs(
            bundle.get("receipts") or [], start, end, "posting_date",
            ("number", "order_number", "posting_date", "vendor_name"),
        ),
        "purchase_invoices": _docs(
            bundle.get("purchase_invoices") or [], start, end, "posting_date",
            ("number", "order_number", "posting_date", "vendor_name", "amount"),
        ),
        "open_invoices": [
            {
                "number": row.get("number"),
                "due_date": row.get("due_date"),
                "amount": row.get("amount"),
                "status": row.get("status"),
            }
            for row in bundle.get("open_invoices") or []
            if (row.get("status") or "Open").lower() in {"open", ""}
        ],
        "quotes": [
            {"number": row.get("number"), "document_date": row.get("document_date"), "amount": row.get("amount")}
            for row in bundle.get("quotes") or []
        ],
        "shipments": _docs(
            bundle.get("shipments") or [], start, end, "posting_date",
            ("number", "order_number", "posting_date", "order_date"),
        ),
        "below_reorder": [
            {
                "item_number": row.get("item_number"),
                "on_hand": row.get("on_hand"),
                "reorder_point": row.get("reorder_point"),
            }
            for row in (operations.get("inventory") or {}).get("below_reorder") or []
        ],
    }


def _money(value: Any) -> str:
    if value is None:
        return "—"
    return f"${float(value):,.2f}"


def _line(label: str, value: Any) -> str:
    return f"{label}: {value if value is not None else '—'}"


def _block(title: str, rows: list[dict], columns: tuple[str, ...]) -> list[str]:
    lines = [f"{title} ({len(rows)})"]
    if not rows:
        lines.append("  (none)")
        return lines
    for row in rows:
        bits = [str(row.get(column) if row.get(column) is not None else "—") for column in columns]
        lines.append("  " + "  ".join(bits))
    return lines


def format_validation_report(trace: dict, *, month: str, as_of: Optional[str] = None) -> str:
    """Plain-text report. One KPI, then the documents that produced it."""
    kpis = trace.get("kpis") or {}
    period = trace.get("period") or {}
    compare = trace.get("comparisons") or {}
    prior = compare.get("prior_month") or {}
    year_ago = compare.get("same_month_last_year") or {}
    lines = [
        f"KPI validation — {month}",
        f"Period: {period.get('from')} to {period.get('to')}",
        f"As of: {as_of or 'live read'}",
        "",
        _line("SO to PO days", kpis.get("so_to_po_days")),
        _line("SO to PO orders over 5 days", kpis.get("so_to_po_late_count")),
        *_block(
            "Sales order / purchase order pairs",
            trace.get("so_po_pairs") or [],
            ("sales_order", "purchase_order", "vendor_name", "days", "po_sent_date"),
        ),
        "",
        _line("Vendor acknowledgement days", kpis.get("ack_days")),
        *_block("Acknowledgement by vendor", trace.get("acknowledgements") or [], ("vendor_name", "count", "average_days")),
        "",
        _line("Unacknowledged purchase orders", kpis.get("unacknowledged_count")),
        *_block(
            "Unacknowledged PO numbers",
            trace.get("unacknowledged_purchase_orders") or [],
            ("number", "vendor_name", "sent_date", "age_days", "amount"),
        ),
        "",
        _line("Vendor on-time percent", kpis.get("on_time_pct")),
        *_block("Purchase receipts in the month", trace.get("receipts") or [], ("number", "order_number", "posting_date", "vendor_name")),
        "",
        _line("Sales", _money(kpis.get("sales"))),
        (
            "Prior month "
            f"{prior.get('from')} to {prior.get('to')}: {_money(kpis.get('sales_prior_month'))} "
            f"({kpis.get('sales_prior_month_delta_pct') if kpis.get('sales_prior_month_delta_pct') is not None else '—'}%)"
        ),
        (
            "Same month last year "
            f"{year_ago.get('from')} to {year_ago.get('to')}: {_money(kpis.get('sales_last_year'))} "
            f"({kpis.get('sales_last_year_delta_pct') if kpis.get('sales_last_year_delta_pct') is not None else '—'}%)"
        ),
        *_block(
            "Posted sales invoices",
            trace.get("sales_invoices") or [],
            ("number", "posting_date", "amount", "customer_name"),
        ),
        *_block("Sales orders dated in the month", trace.get("sales_orders") or [], ("number", "order_date", "amount", "customer_name")),
        "",
        _line("Quote conversion percent", kpis.get("quote_conversion_pct")),
        _line("Open quote value", _money(kpis.get("open_quote_value"))),
        *_block("Open quotes", trace.get("quotes") or [], ("number", "document_date", "amount")),
        "",
        _line("Gross margin percent", kpis.get("margin_pct")),
        _line("Invoice vs PO", _money(kpis.get("po_variance"))),
        *_block(
            "Posted purchase invoices",
            trace.get("purchase_invoices") or [],
            ("number", "order_number", "posting_date", "vendor_name", "amount"),
        ),
        "",
        _line("Accounts receivable", _money(kpis.get("ar_total"))),
        *_block("Open sales invoices", trace.get("open_invoices") or [], ("number", "due_date", "amount", "status")),
        "",
        _line("Open order backlog", _money(kpis.get("backlog"))),
        _line("Order to ship days", kpis.get("order_to_ship_days")),
        *_block("Shipments in the month", trace.get("shipments") or [], ("number", "order_number", "posting_date", "order_date")),
        "",
        _line("Inventory value", _money(kpis.get("inventory_value"))),
        _line("Below reorder count", kpis.get("below_reorder_count")),
        *_block("Items below reorder", trace.get("below_reorder") or [], ("item_number", "on_hand", "reorder_point")),
        "",
        _line("Freight percent of sales", kpis.get("freight_pct")),
    ]
    return "\n".join(lines) + "\n"
