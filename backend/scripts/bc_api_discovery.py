"""
BC API Discovery Tool
Discovers and tests available BC API endpoints including production-related ones.

Usage:
    python scripts/bc_api_discovery.py --discover
    python scripts/bc_api_discovery.py --test-production
    python scripts/bc_api_discovery.py --export-har
"""

import sys
import os
import json
import re
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional
import urllib.parse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from app.integrations.bc.client import bc_client


class BCAPIDiscovery:
    """Discover and document BC API endpoints"""

    def __init__(self):
        self.bc = bc_client
        self.base_url = "https://api.businesscentral.dynamics.com/v2.0/f791be27-77c5-4334-88d0-cfc053e4f091/Sandbox_Internal"
        self.company_name = "Open Distribution Company Inc."
        self.company_id = bc_client.company_id
        self.token = None
        self.discovered_endpoints = {}
        self.har_entries = []

    def _get_token(self) -> str:
        if not self.token:
            self.token = self.bc._get_access_token()
        return self.token

    def _get_headers(self, accept: str = "application/json") -> Dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": accept
        }

    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make request and capture for HAR-like export"""
        start_time = datetime.utcnow()

        headers = kwargs.pop("headers", self._get_headers())
        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)

        end_time = datetime.utcnow()

        # Capture HAR-like entry
        self.har_entries.append({
            "startedDateTime": start_time.isoformat() + "Z",
            "time": (end_time - start_time).total_seconds() * 1000,
            "request": {
                "method": method,
                "url": url,
                "headers": [{"name": k, "value": v} for k, v in headers.items() if k != "Authorization"]
            },
            "response": {
                "status": response.status_code,
                "statusText": response.reason,
                "headers": [{"name": k, "value": v} for k, v in response.headers.items()],
                "content": {
                    "size": len(response.content),
                    "mimeType": response.headers.get("Content-Type", ""),
                    "text": response.text[:10000] if len(response.text) < 50000 else "[truncated]"
                }
            }
        })

        return response

    def discover_all_apis(self) -> Dict[str, Any]:
        """Discover all available API endpoints"""
        print("=" * 60)
        print("BC API Discovery")
        print("=" * 60)

        results = {
            "discovered_at": datetime.utcnow().isoformat(),
            "company": self.company_name,
            "apis": {}
        }

        # 1. Standard API v2.0
        print("\n[1/4] Checking Standard API v2.0...")
        results["apis"]["v2.0"] = self._discover_api_surface("/api/v2.0")

        # 2. Standard API v1.0
        print("\n[2/4] Checking Standard API v1.0...")
        results["apis"]["v1.0"] = self._discover_api_surface("/api/v1.0")

        # 3. ODataV4 (Web Services)
        print("\n[3/4] Checking ODataV4 Web Services...")
        results["apis"]["ODataV4"] = self._discover_odata_surface()

        # 4. Automation API
        print("\n[4/4] Checking Automation API...")
        results["apis"]["automation"] = self._discover_api_surface("/api/microsoft/automation/v2.0")

        self.discovered_endpoints = results
        return results

    def _discover_api_surface(self, api_path: str) -> Dict[str, Any]:
        """Discover entities and actions for an API"""
        result = {
            "path": api_path,
            "entities": [],
            "actions": [],
            "production_related": []
        }

        # Get metadata
        url = f"{self.base_url}{api_path}/$metadata"
        resp = self._make_request("GET", url, headers=self._get_headers("application/xml"))

        if resp.status_code != 200:
            result["error"] = f"Failed to get metadata: {resp.status_code}"
            return result

        metadata = resp.text

        # Parse entities
        entities = re.findall(r'<EntitySet[^>]*Name="([^"]+)"', metadata)
        result["entities"] = sorted(set(entities))

        # Parse actions
        actions = re.findall(r'<Action[^>]*Name="([^"]+)"', metadata)
        result["actions"] = sorted(set(actions))

        # Find production-related
        prod_keywords = ['prod', 'manufacturing', 'bom', 'routing', 'work', 'machine', 'capacity']
        for entity in result["entities"]:
            if any(kw in entity.lower() for kw in prod_keywords):
                result["production_related"].append(entity)

        print(f"  Found {len(result['entities'])} entities, {len(result['actions'])} actions")
        if result["production_related"]:
            print(f"  Production-related: {result['production_related']}")

        return result

    def _discover_odata_surface(self) -> Dict[str, Any]:
        """Discover ODataV4 web services"""
        result = {
            "path": "/ODataV4",
            "entities": [],
            "entities_with_data": [],
            "production_related": []
        }

        # Get metadata
        url = f"{self.base_url}/ODataV4/$metadata"
        resp = self._make_request("GET", url, headers=self._get_headers("application/xml"))

        if resp.status_code != 200:
            result["error"] = f"Failed to get metadata: {resp.status_code}"
            return result

        metadata = resp.text
        entities = re.findall(r'<EntitySet[^>]*Name="([^"]+)"', metadata)
        result["entities"] = sorted(set(entities))

        # Test which have data
        encoded_company = urllib.parse.quote(self.company_name)
        print(f"  Testing {len(result['entities'])} entities for data...")

        for entity in result["entities"]:
            try:
                url = f"{self.base_url}/ODataV4/Company('{encoded_company}')/{entity}?$top=1"
                resp = self._make_request("GET", url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("value"):
                        result["entities_with_data"].append(entity)

                        # Check for production-related
                        if any(kw in entity.lower() for kw in ['prod', 'bom', 'manufacturing']):
                            result["production_related"].append({
                                "name": entity,
                                "sample_fields": list(data["value"][0].keys())[:10]
                            })
            except:
                pass

        print(f"  {len(result['entities_with_data'])} entities have data")
        return result

    def test_production_endpoints(self) -> Dict[str, Any]:
        """Test specific production-related endpoints"""
        print("\n" + "=" * 60)
        print("Testing Production-Related Endpoints")
        print("=" * 60)

        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "endpoints_tested": [],
            "working": [],
            "not_found": []
        }

        encoded_company = urllib.parse.quote(self.company_name)

        # Endpoints to test
        test_endpoints = [
            # ODataV4 patterns
            ("ODataV4", f"/ODataV4/Company('{encoded_company}')/ProductionBomLines"),
            ("ODataV4", f"/ODataV4/Company('{encoded_company}')/Production_BOM_Excel"),
            ("ODataV4", f"/ODataV4/Company('{encoded_company}')/ReleasedProductionOrders"),
            ("ODataV4", f"/ODataV4/Company('{encoded_company}')/ProductionOrders"),
            ("ODataV4", f"/ODataV4/Company('{encoded_company}')/FirmPlannedProdOrders"),

            # API v2.0 patterns (if custom published)
            ("API v2.0", f"/api/v2.0/companies({self.company_id})/productionOrders"),
            ("API v2.0", f"/api/v2.0/companies({self.company_id})/releasedProductionOrders"),

            # Custom API patterns
            ("Custom", f"/api/opendc/v1.0/companies({self.company_id})/productionOrders"),
            ("Custom", f"/api/probiztech/v1.0/companies({self.company_id})/productionOrders"),
        ]

        for api_type, endpoint in test_endpoints:
            url = f"{self.base_url}{endpoint}?$top=1"
            results["endpoints_tested"].append({"type": api_type, "endpoint": endpoint})

            try:
                resp = self._make_request("GET", url)
                if resp.status_code == 200:
                    data = resp.json()
                    count = len(data.get("value", []))
                    results["working"].append({
                        "type": api_type,
                        "endpoint": endpoint,
                        "record_count": count,
                        "sample_fields": list(data["value"][0].keys()) if count > 0 else []
                    })
                    print(f"  [OK] {api_type}: {endpoint.split('/')[-1]} ({count} records)")
                else:
                    results["not_found"].append({
                        "type": api_type,
                        "endpoint": endpoint,
                        "status": resp.status_code
                    })
                    print(f"  [--] {api_type}: {endpoint.split('/')[-1]} ({resp.status_code})")
            except Exception as e:
                results["not_found"].append({
                    "type": api_type,
                    "endpoint": endpoint,
                    "error": str(e)
                })
                print(f"  [ERR] {api_type}: {endpoint.split('/')[-1]} (Error)")

        return results

    def export_har(self, filename: str = None) -> str:
        """Export captured requests as HAR file"""
        if not filename:
            filename = f"bc_api_capture_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.har"

        har_data = {
            "log": {
                "version": "1.2",
                "creator": {
                    "name": "BC API Discovery",
                    "version": "1.0"
                },
                "entries": self.har_entries
            }
        }

        filepath = os.path.join(os.path.dirname(__file__), "..", "docs", filename)
        with open(filepath, "w") as f:
            json.dump(har_data, f, indent=2)

        print(f"\nHAR file exported: {filepath}")
        print(f"Captured {len(self.har_entries)} requests")
        return filepath

    def export_discovery_report(self, filename: str = None) -> str:
        """Export discovery results as JSON"""
        if not filename:
            filename = f"bc_api_discovery_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"

        filepath = os.path.join(os.path.dirname(__file__), "..", "docs", filename)
        with open(filepath, "w") as f:
            json.dump(self.discovered_endpoints, f, indent=2)

        print(f"\nDiscovery report exported: {filepath}")
        return filepath


def main():
    parser = argparse.ArgumentParser(description="BC API Discovery Tool")
    parser.add_argument("--discover", action="store_true", help="Discover all API endpoints")
    parser.add_argument("--test-production", action="store_true", help="Test production-related endpoints")
    parser.add_argument("--export-har", action="store_true", help="Export HAR file of API calls")
    parser.add_argument("--all", action="store_true", help="Run all discovery and tests")

    args = parser.parse_args()

    if not any([args.discover, args.test_production, args.export_har, args.all]):
        parser.print_help()
        return

    discovery = BCAPIDiscovery()

    if args.all or args.discover:
        discovery.discover_all_apis()
        discovery.export_discovery_report()

    if args.all or args.test_production:
        results = discovery.test_production_endpoints()

        print("\n" + "=" * 60)
        print("Production Endpoint Summary")
        print("=" * 60)
        print(f"Working endpoints: {len(results['working'])}")
        for ep in results['working']:
            print(f"  - {ep['endpoint'].split('/')[-1]}")
        print(f"\nNot available: {len(results['not_found'])}")

    if args.all or args.export_har:
        discovery.export_har()

    print("\nDone!")


if __name__ == "__main__":
    main()
