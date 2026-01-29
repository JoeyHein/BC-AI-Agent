"""
Explore Hardware Kit (HK) Part Numbers in Business Central
"""

import sys
from pathlib import Path
import requests
import json
from collections import defaultdict
import re

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import settings


class BCAPIClient:
    def __init__(self):
        self.tenant_id = settings.BC_TENANT_ID
        self.client_id = settings.BC_CLIENT_ID
        self.client_secret = settings.BC_CLIENT_SECRET
        self.environment = settings.BC_ENVIRONMENT
        self.company_id = settings.BC_COMPANY_ID
        self.base_url = settings.BC_BASE_URL
        self.access_token = None

    def authenticate(self):
        print("Authenticating with Business Central...")
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://api.businesscentral.dynamics.com/.default",
            "grant_type": "client_credentials"
        }
        response = requests.post(token_url, data=data)
        if response.status_code == 200:
            self.access_token = response.json()["access_token"]
            print("Authentication successful!")
            return True
        else:
            print(f"Authentication failed: {response.status_code}")
            return False

    def get_headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def search_items(self, filter_query=None, top=500):
        url = f"{self.base_url}/{self.tenant_id}/{self.environment}/api/v2.0/companies({self.company_id})/items"
        params = {"$top": top}
        if filter_query:
            params["$filter"] = filter_query
        response = requests.get(url, headers=self.get_headers(), params=params)
        if response.status_code == 200:
            return response.json().get("value", [])
        else:
            print(f"Failed to fetch items: {response.status_code}")
            return []


def extract_hk_prefix(item_number):
    match = re.match(r"^(HK[0-9]{2})", item_number)
    if match:
        return match.group(1)
    return None


def main():
    sep = "=" * 100
    dash = "-" * 80
    
    print(sep)
    print("BC Hardware Kit (HK) Part Number Discovery")
    print(sep)

    client = BCAPIClient()
    if not client.authenticate():
        return

    print("\nQuerying items starting with HK...")
    items = client.search_items(filter_query="startswith(number,'HK')", top=1000)
    
    if not items:
        print("No HK items found!")
        return
    
    print(f"Found {len(items)} HK items\n")

    grouped_items = defaultdict(list)
    for item in items:
        number = item.get("number", "")
        prefix = extract_hk_prefix(number)
        if prefix:
            grouped_items[prefix].append(item)
        else:
            grouped_items["OTHER"].append(item)
    
    sorted_prefixes = sorted(grouped_items.keys())
    
    print("\n" + sep)
    print("ALL HARDWARE KITS BY PREFIX")
    print(sep)
    
    for prefix in sorted_prefixes:
        items_list = grouped_items[prefix]
        print(f"\n{prefix} - {len(items_list)} items")
        print(dash)
        for item in sorted(items_list, key=lambda x: x.get("number", "")):
            number = item.get("number", "")
            name = item.get("displayName", "")
            price = item.get("unitPrice", 0)
            print(f"  {number:30} ${price:10.2f}  {name}")
    
    print("\n\n" + sep)
    print("PATTERN ANALYSIS - DIGIT MEANINGS")
    print(sep)
    
    first_digit_groups = defaultdict(list)
    for prefix in sorted_prefixes:
        if prefix.startswith("HK") and len(prefix) >= 4:
            first_digit = prefix[2]
            first_digit_groups[first_digit].append({
                "prefix": prefix,
                "count": len(grouped_items[prefix]),
                "sample_desc": grouped_items[prefix][0].get("displayName", "") if grouped_items[prefix] else ""
            })
    
    print("\nGrouped by FIRST digit (HKx_):")
    print(dash)
    for digit in sorted(first_digit_groups.keys()):
        group = first_digit_groups[digit]
        print(f"\nFirst Digit = {digit}:")
        for item in group:
            desc = item["sample_desc"][:70]
            print(f"  {item['prefix']}: {item['count']} items - {desc}")
    
    second_digit_groups = defaultdict(list)
    for prefix in sorted_prefixes:
        if prefix.startswith("HK") and len(prefix) >= 4:
            second_digit = prefix[3]
            second_digit_groups[second_digit].append({
                "prefix": prefix,
                "count": len(grouped_items[prefix]),
                "sample_desc": grouped_items[prefix][0].get("displayName", "") if grouped_items[prefix] else ""
            })
    
    print("\n\nGrouped by SECOND digit (HK_x):")
    print(dash)
    for digit in sorted(second_digit_groups.keys()):
        group = second_digit_groups[digit]
        print(f"\nSecond Digit = {digit}:")
        for item in group:
            desc = item["sample_desc"][:70]
            print(f"  {item['prefix']}: {item['count']} items - {desc}")
    
    export_data = {}
    for prefix in sorted_prefixes:
        export_data[prefix] = []
        for item in grouped_items[prefix]:
            export_data[prefix].append({
                "number": item.get("number", ""),
                "displayName": item.get("displayName", ""),
                "unitPrice": item.get("unitPrice", 0),
                "unitCost": item.get("unitCost", 0),
            })
    
    output_file = Path(__file__).parent.parent / "data" / "hardware_kits_analysis.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(export_data, f, indent=2)
    print(f"\nRaw data exported to: {output_file}")


if __name__ == "__main__":
    main()
