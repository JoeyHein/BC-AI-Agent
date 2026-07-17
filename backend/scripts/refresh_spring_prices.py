"""Refresh the spring price book from Business Central.

Writes app/services/spring_price_book.json — a flat {part_number: unit_price} map
used by spring_pricing.assembly_cost() to pick the cheapest spring assembly that
still meets the cycle target and fits the shaft.

Only prices we can trust land in the book: blocked items and anything priced <= 0
are dropped. A $0 item that stayed in the book would look free and win every
comparison (e.g. SP11-25036-01/-02, which are live in BC at $0.00).

Run from backend/:
    python -m scripts.refresh_spring_prices          # write the book
    python -m scripts.refresh_spring_prices --dry    # print, don't write
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.integrations.bc.client import BusinessCentralClient

# Prefixes worth pricing: SP11 springs, SP12 winder sets + couplers,
# PK14 PVC tube (6" springs only).
PREFIXES = ("SP11-", "SP12-", "PK14-")

OUT_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "spring_price_book.json"


def fetch_prices(bc: BusinessCentralClient) -> tuple:
    prices: dict = {}
    dropped: list = []
    cid = bc.company_id
    for prefix in PREFIXES:
        # Follow @odata.nextLink so a prefix with >1 page isn't silently
        # truncated (a missing winder/coupler price silently disables cost-aware
        # selection for every candidate that needs it).
        url = (
            f"{bc.base_url}/companies({cid})/items"
            f"?$filter=startswith(number,'{prefix}')&$top=1000"
        )
        for item in bc._paginate_v2(url, f"{prefix} items"):
            number = item.get("number") or ""
            price = item.get("unitPrice")
            if item.get("blocked"):
                dropped.append(f"{number} (blocked)")
                continue
            if not price or price <= 0:
                dropped.append(f"{number} (${price})")
                continue
            prices[number] = float(price)
    return prices, dropped


def main() -> int:
    dry = "--dry" in sys.argv
    bc = BusinessCentralClient()
    prices, dropped = fetch_prices(bc)

    if not prices:
        print("ERROR: no priced items returned from BC — refusing to write an empty book")
        return 1

    book = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Business Central items API",
        "note": "Blocked and $0-priced items are excluded on purpose — see module docstring.",
        "prices": dict(sorted(prices.items())),
    }

    print(f"priced items: {len(prices)}")
    print(f"excluded:     {len(dropped)}")
    for d in sorted(dropped)[:20]:
        print(f"   - {d}")

    if dry:
        print("\n--dry: not written")
        return 0

    OUT_PATH.write_text(json.dumps(book, indent=1) + "\n")
    print(f"\nwrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
