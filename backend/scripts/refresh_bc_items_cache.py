"""
Refresh data/bc_analysis/bc_items.json from BC's production OData feed.

Usage (from backend/):
    python -m scripts.refresh_bc_items_cache

Uses the configured bc_client (production env per .env) and paginates the
items endpoint. Drops the result on top of the existing cache so downstream
mappers (bc_part_number_mapper.py) and the customer portal's AI substitute
search both see the latest catalog.
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.integrations.bc.client import bc_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("refresh_bc_items")

OUT = Path(__file__).resolve().parent.parent / "data" / "bc_analysis" / "bc_items.json"
BATCH = 500


def fetch_all_items():
    items = []
    skip = 0
    while True:
        endpoint = f"companies({bc_client.company_id})/items?$top={BATCH}&$skip={skip}"
        result = bc_client._make_request("GET", endpoint)
        page = result.get("value", [])
        if not page:
            break
        items.extend(page)
        log.info(f"  fetched {len(items)} items so far...")
        if len(page) < BATCH and "@odata.nextLink" not in result:
            break
        skip += BATCH
    return items


def main():
    log.info(f"Pulling all items from BC company {bc_client.company_id}...")
    items = fetch_all_items()
    log.info(f"Total: {len(items)} items")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, default=str)
    log.info(f"Wrote {OUT}")

    # Quick sanity: count HK13 SKUs by HH bucket so we can see the new ones land.
    hk13 = [i for i in items if (i.get("number") or "").startswith("HK13-")]
    buckets = {}
    for i in hk13:
        n = i["number"]
        if len(n) >= 7:
            buckets.setdefault(n[5:7], 0)
            buckets[n[5:7]] += 1
    log.info(f"HK13 SKUs: {len(hk13)} total | by HH bucket: {dict(sorted(buckets.items()))}")


if __name__ == "__main__":
    main()
