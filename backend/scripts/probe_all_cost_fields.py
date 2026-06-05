"""Find every cost-shaped field BC exposes for an item across api/v2.0
and any OData V4 page that includes it. Goal: confirm whether $95 is the
'standard cost' BC uses for pricing while a different field holds the
real last-paid cost."""
import sys
import re
import requests
from app.integrations.bc.client import BusinessCentralClient


def main():
    item_no = sys.argv[1] if len(sys.argv) > 1 else "GK16-23205-00"
    bc = BusinessCentralClient()
    headers = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}
    seg = bc._odata_v4_company_segment(None)
    safe = item_no.replace("'", "''")

    # Find every entity in metadata that has both a key/identifier matching
    # an item AND any field with 'cost' in the name
    meta = requests.get(f"{bc.odata_url}/$metadata",
                        headers={**headers, "Accept": "application/xml"},
                        timeout=30).text
    cost_entities = []
    for m in re.finditer(r'<EntityType Name="([^"]+)">(.*?)</EntityType>', meta, re.DOTALL):
        name, body = m.group(1), m.group(2)
        cost_props = re.findall(r'<Property Name="([^"]+)" Type="([^"]+)"', body)
        cost_named = [p for p in cost_props if "cost" in p[0].lower()]
        if cost_named and any(p[0] in ("No", "Item_No", "Product_No", "number") for p in cost_props):
            cost_entities.append((name, cost_named))

    print(f"Entities with cost fields keyed on item:")
    for name, cost_named in cost_entities:
        print(f"  {name}:")
        for prop, typ in cost_named:
            print(f"    {prop} ({typ})")

    # Print all numeric fields on the api/v2.0 item too — last_paid might
    # be exposed as e.g. lastDirectCost
    url1 = f"{bc.base_url}/companies({bc.company_id})/items?$filter=number eq '{safe}'"
    r1 = requests.get(url1, headers=headers, timeout=30)
    if r1.json().get("value"):
        item = r1.json()["value"][0]
        print(f"\nALL numeric fields on api/v2.0 item {item_no}:")
        for k, v in sorted(item.items()):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                print(f"  {k:35} {v!r}")


if __name__ == "__main__":
    main()
