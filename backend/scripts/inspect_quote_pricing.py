"""
For a given BC quote (e.g. SQ-002486), compare:
  1. The unitPrice currently on each line (what the portal patched in)
  2. What BC's SalesPriceLists hierarchy would resolve to right now
  3. The legacy margin-engine's price (what the portal would compute)
  4. Item.unitCost (for sanity)

Surfaces exactly where the portal is overriding BC's customer-specific
Sales Prices.
"""
import sys
import requests
from app.integrations.bc.client import BusinessCentralClient
from app.api.pricing_diagnostic import _resolve_bc_hierarchy
from app.services.pricing_service import (
    calculate_selling_price, warm_bc_cost_cache, _get_live_item,
)
from app.db.database import SessionLocal
from app.db.models import BCCustomer


def find_quote(bc, quote_no):
    """Find a quote by its number (e.g. 'SQ-002486')."""
    seg = f"companies({bc.company_id})"
    safe = quote_no.replace("'", "''")
    url = f"{bc.base_url}/{seg}/salesQuotes?$filter=number eq '{safe}'&$top=1"
    headers = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code >= 400:
        print(f"HTTP {r.status_code}: {r.text[:200]}")
        return None
    rows = r.json().get("value", [])
    return rows[0] if rows else None


def main():
    quote_no = sys.argv[1] if len(sys.argv) > 1 else "SQ-002486"
    bc = BusinessCentralClient()
    db = SessionLocal()

    quote = find_quote(bc, quote_no)
    if not quote:
        print(f"Quote {quote_no} not found.")
        return

    print(f"Quote {quote_no} | id={quote['id']}")
    print(f"  customer        : #{quote.get('customerNumber')} {quote.get('customerName')!r}")
    print(f"  customer GUID   : {quote.get('customerId')}")
    print(f"  status          : {quote.get('status')}")
    print(f"  total ex tax    : ${quote.get('totalAmountExcludingTax', 0):,.2f}")
    print()

    # Pull the customer's live BC price group (authoritative)
    cust_no = quote.get("customerNumber") or ""
    live_group = bc.get_customer_price_group(cust_no) if cust_no else None
    print(f"  live BC price group for #{cust_no}: {live_group!r}")

    # Local cache view
    bc_cust = db.query(BCCustomer).filter(
        BCCustomer.bc_customer_id == quote.get("customerId")
    ).first()
    local_tier = bc_cust.pricing_tier if bc_cust else None
    print(f"  local tier      : {local_tier!r}")
    print()

    # Pull lines
    lines = bc.get_quote_lines(quote["id"])
    item_lines = [l for l in lines if l.get("lineType") == "Item"]
    print(f"Item lines on quote: {len(item_lines)}")
    print()

    # Warm cost cache
    part_numbers = [l.get("lineObjectNumber") for l in item_lines if l.get("lineObjectNumber")]
    warm_bc_cost_cache(part_numbers)

    print(f"{'Part':25} {'Qty':>5} {'Group':6} {'Cost':>10} {'On Quote':>10} "
          f"{'BC SalesPrice':>14} {'BC Lvl':>20} {'Legacy':>10} {'Quote-vs-BC $':>14}")
    print("-" * 130)

    delta_total = 0.0
    overwritten = 0
    for line in item_lines:
        part = line.get("lineObjectNumber") or ""
        qty = line.get("quantity") or 0
        on_quote_price = line.get("unitPrice") or 0
        item = _get_live_item(part) or {}
        cost = item.get("unitCost") or 0
        posting = item.get("generalProductPostingGroupCode") or ""

        # What BC would resolve right now
        hier = _resolve_bc_hierarchy(
            bc_client=bc, item_no=part, customer_no=cust_no,
            customer_price_group=live_group, qty=qty, as_of_date="2026-05-06",
            item_unit_price_fallback=item.get("unitPrice"),
        )
        bc_price = hier["resolved_price"]
        bc_level = hier["resolved_level"]

        # Legacy
        try:
            legacy = calculate_selling_price(part, "commercial", local_tier or "retail", db)
        except Exception:
            legacy = None

        delta = (on_quote_price - (bc_price or 0)) * qty if bc_price else 0
        delta_total += delta
        if bc_price is not None and abs(on_quote_price - bc_price) > 0.01:
            overwritten += 1

        bc_price_str = f"${bc_price:,.2f}" if bc_price is not None else "-"
        legacy_str = f"${legacy:,.2f}" if legacy is not None else "-"
        print(f"{part[:25]:25} {qty:>5.1f} {posting:6} ${cost:>9.2f} ${on_quote_price:>9.2f} "
              f"{bc_price_str:>14} {str(bc_level)[:20]:>20} {legacy_str:>10} ${delta:>13.2f}")

    print("-" * 130)
    print(f"\n{overwritten} of {len(item_lines)} lines differ from BC SalesPriceLists "
          f"(quote total deviation from BC = ${delta_total:,.2f})")

    db.close()


if __name__ == "__main__":
    main()
