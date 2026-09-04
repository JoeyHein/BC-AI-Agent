"""
Audit GK15 residential glass-kit lines on open sales orders and recent posted
invoices for parts that couldn't have come out of our own part generator.

Background: SO-001146 (2026-05-22) shipped with GK15-12605-50, a "SLIM
WINDOW" glass kit whose ss/glass-type digits (12/6) don't match anything
_get_window_parts() produces (ss is always 10/11 for Kanata, 55 for Craft;
glass digit is always 1/2/4/9). That means the line was hand-typed directly
in BC, bypassing the app entirely — and the door's printed weight/spring
sizing (204 lbs, "TOP SECTION ONE WINDOW CENTERED") reflects whatever window
config was in the app *before* that manual substitution, not the single slim
window actually on the order. See project_door_weight_calculator memory for
the full writeup.

This script can't catch it at the time of the edit (the app has no
visibility into direct BC edits) — it's a periodic reconciliation sweep, not
an inline guard. Run it every so often, or after a batch of Kanata/Craft
window orders, to catch drift before/after it ships.

Usage:
    python scripts/audit_glass_kit_parts.py                  # open orders + invoices since 90 days ago
    python scripts/audit_glass_kit_parts.py --since 2026-01-01
    python scripts/audit_glass_kit_parts.py --order SO-001146 # check one order/invoice by number
"""
import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from app.integrations.bc.client import BusinessCentralClient
from app.services.part_number_service import is_generatable_glass_kit_part

SERIES_RE = re.compile(r"KANATA|CRAFT", re.IGNORECASE)


def _door_series_for_line(lines, gk15_line_index):
    """Look backward from a GK15 line for the most recent door-description
    Comment line (e.g. "(3) 9'0\" x 7'0\" KANATA, BLACK, ...") to recover the
    series. Falls back to KANATA if none is found."""
    for l in reversed(lines[:gk15_line_index]):
        if l.get("lineType") != "Comment":
            continue
        m = SERIES_RE.search(l.get("description") or "")
        if m:
            return m.group(0).upper()
    return "KANATA"


def _scan_lines(order_or_invoice_number, lines, flagged):
    for i, l in enumerate(lines):
        num = l.get("lineObjectNumber") or l.get("number") or ""
        if not isinstance(num, str) or not num.upper().startswith("GK15-"):
            continue
        series = _door_series_for_line(lines, i)
        ok, reason = is_generatable_glass_kit_part(num, series)
        if not ok:
            flagged.append({
                "document": order_or_invoice_number,
                "part_number": num,
                "series": series,
                "reason": reason,
                "description": (l.get("description") or "")[:80],
            })


def audit_open_orders(bc: BusinessCentralClient, flagged: list):
    orders = bc.get_open_sales_orders_with_lines()
    for o in orders:
        _scan_lines(o.get("number"), o.get("salesOrderLines", []), flagged)
    return len(orders)


def audit_posted_invoices(bc: BusinessCentralClient, since_date: str, flagged: list):
    invs = bc.get_posted_sales_invoices(since_date=since_date)
    order_nos = sorted(set(i.get("Order_No") for i in invs if i.get("Order_No")))
    cid = bc.company_id
    for on in order_nos:
        v2invs = bc.get_invoices_for_order(on)
        if not v2invs:
            continue
        inv_id = v2invs[0]["id"]
        lines = bc._make_request(
            "GET", f"companies({cid})/salesInvoices({inv_id})/salesInvoiceLines"
        ).get("value", [])
        _scan_lines(on, lines, flagged)
    return len(order_nos)


def audit_single_order(bc: BusinessCentralClient, order_number: str, flagged: list):
    order = bc.get_sales_order_by_number(order_number)
    if order:
        lines = bc.get_order_lines(order["id"])
        _scan_lines(order_number, lines, flagged)
        return True
    v2invs = bc.get_invoices_for_order(order_number)
    if v2invs:
        cid = bc.company_id
        lines = bc._make_request(
            "GET", f"companies({cid})/salesInvoices({v2invs[0]['id']})/salesInvoiceLines"
        ).get("value", [])
        _scan_lines(order_number, lines, flagged)
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default=None, help="ISO date; posted invoices on/after this date (default: 90 days ago)")
    parser.add_argument("--order", default=None, help="Check a single order/invoice number instead of sweeping")
    args = parser.parse_args()

    bc = BusinessCentralClient()
    flagged = []

    if args.order:
        found = audit_single_order(bc, args.order, flagged)
        if not found:
            print(f"{args.order}: not found as an open sales order or posted invoice")
            return
    else:
        since = args.since or (date.today() - timedelta(days=90)).isoformat()
        n_open = audit_open_orders(bc, flagged)
        n_inv = audit_posted_invoices(bc, since, flagged)
        print(f"Scanned {n_open} open sales orders and {n_inv} posted invoices (since {since}).")

    if not flagged:
        print("No non-generatable glass-kit parts found.")
        return

    print(f"\n{len(flagged)} flagged line(s) - window part doesn't match anything our generator produces:")
    for f in flagged:
        print(f"  {f['document']} | {f['part_number']} | {f['series']} | {f['reason']}")
        print(f"      {f['description']}")
    print(
        "\nThese doors' printed weight/spring sizing may be stale relative to what's "
        "actually on the quote - verify against the current window config before shipping."
    )


if __name__ == "__main__":
    main()
