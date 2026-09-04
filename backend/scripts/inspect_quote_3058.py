"""Read-only dump of a single quote's lines, for the high-lift consistency investigation."""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.integrations.bc.client import BusinessCentralClient


def find_quote_by_number(bc, number):
    cid = bc.company_id
    res = bc._make_request("GET", f"companies({cid})/salesQuotes?$filter=number eq '{number}'")
    vals = res.get("value", [])
    return vals[0] if vals else None


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else "3058"
    number = raw if raw.upper().startswith("SQ-") else f"SQ-{int(raw):06d}"

    bc = BusinessCentralClient()
    quote = find_quote_by_number(bc, number)
    if not quote:
        print(f"!! Quote {number} not found")
        return 1

    qid = quote["id"]
    print(f"=== {number} ===")
    print(f"  customer: {quote.get('customerName')} ({quote.get('customerNumber')})")
    print(f"  status  : {quote.get('status')}")
    print(f"  doc date: {quote.get('documentDate')}")

    lines = bc.get_quote_lines(qid)
    print(f"  lines   : {len(lines)}\n")
    print(f"{'PART':<20}{'QTY':>5}{'UNIT$':>11}  DESC")
    print("-" * 100)
    for ql in lines:
        pn = ql.get("lineObjectNumber", "")
        qty = ql.get("quantity", 0) or 0
        price = ql.get("unitPrice", 0) or 0
        desc = ql.get("description", "")
        tag = "(comment)" if ql.get("lineType") == "Comment" else pn
        print(f"{tag:<20}{qty:>5}{price:>11.2f}  {desc[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
