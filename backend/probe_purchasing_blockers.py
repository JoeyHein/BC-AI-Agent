"""Re-check the 3 purchasing-tool blockers against the live Production tenant.

All checks are READ-ONLY. Mail.Send is verified by decoding the Graph token's
`roles` claim (no email is actually sent).
"""
import base64
import json
import urllib.parse

import requests

from app.integrations.bc.client import bc_client
from app.services.bc_production_service import bc_production_service, ODATA_ENDPOINTS
from app.integrations.email.client import graph_client


def _odata_probe(endpoint: str) -> str:
    encoded = urllib.parse.quote(bc_production_service.company_name)
    url = f"{bc_production_service.odata_base}/Company('{encoded}')/{endpoint}?$top=1"
    try:
        tok = bc_client._get_access_token()
        r = requests.get(url, headers={"Authorization": f"Bearer {tok}",
                                       "Accept": "application/json"}, timeout=30)
        if r.status_code == 200:
            n = len(r.json().get("value", []))
            return f"HTTP 200  OK ({n} row sample)"
        return f"HTTP {r.status_code}  {r.text[:120]}"
    except Exception as e:
        return f"ERROR {e}"


def _decode_roles() -> list:
    tok = graph_client._get_access_token()
    payload = tok.split(".")[1]
    payload += "=" * (-len(payload) % 4)  # pad base64
    claims = json.loads(base64.urlsafe_b64decode(payload))
    return claims.get("roles", [])


def main():
    print("=" * 60)
    print("PURCHASING TOOL — BLOCKER RE-CHECK")
    print("=" * 60)

    print("\n[1] Production web services (production-component demand)")
    for label in ("production_orders", "components"):
        ep = ODATA_ENDPOINTS[label]
        print(f"    {ep:28} -> {_odata_probe(ep)}")

    print("\n[2] Item->vendor web service (authoritative Vendor_No)")
    for ep in ("Items", "ItemCard", "ItemList"):
        print(f"    {ep:28} -> {_odata_probe(ep)}")

    print("\n[3] Graph Mail.Send application permission")
    try:
        roles = _decode_roles()
        has = "Mail.Send" in roles
        print(f"    roles on token: {roles}")
        print(f"    Mail.Send granted: {'YES ✅' if has else 'NO ❌'}")
    except Exception as e:
        print(f"    ERROR decoding Graph token: {e}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
