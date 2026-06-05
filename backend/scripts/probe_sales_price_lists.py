"""One-off probe: discover the SalesPriceLists OData entity schema and sample row."""
import re
import json
import requests
from app.integrations.bc.client import BusinessCentralClient


def main():
    bc = BusinessCentralClient()
    token = bc._get_access_token()
    headers_xml = {"Authorization": f"Bearer {token}", "Accept": "application/xml"}
    headers_json = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    meta_url = f"{bc.odata_url}/$metadata"
    r = requests.get(meta_url, headers=headers_xml, timeout=30)
    m = re.search(r'<EntityType Name="SalesPriceLists">(.*?)</EntityType>', r.text, re.DOTALL)
    if m:
        block = m.group(1)
        props = re.findall(r'<Property Name="([^"]+)" Type="([^"]+)"', block)
        print("Fields on SalesPriceLists:")
        for name, typ in props:
            print(f"  {name:35} {typ}")
    else:
        print("SalesPriceLists not in metadata.")

    print("\n--- Sample rows (top 2) ---")
    seg = bc._odata_v4_company_segment(None)
    sample_url = f"{bc.odata_url}/{seg}/SalesPriceLists?$top=2"
    r2 = requests.get(sample_url, headers=headers_json, timeout=30)
    print(f"Status: {r2.status_code}")
    print(json.dumps(r2.json(), indent=2, default=str)[:4000])


if __name__ == "__main__":
    main()
