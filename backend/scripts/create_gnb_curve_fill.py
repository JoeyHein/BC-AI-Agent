#!/usr/bin/env python3
"""Fill the upper curve bands using TX450 (TX500 panels aren't stocked in BC)."""
import json, time, requests

API_BASE = "http://localhost:8000"
GNB_BC_ID = "318ad8fb-4003-f011-9346-0022483d305e"
HW = {"tracks": True, "springs": True, "struts": True, "hardwareKits": True,
      "weatherStripping": True, "bottomRetainer": True, "shafts": True}


def big_tx450(count):
    return {"doorType": "commercial", "doorSeries": "TX450", "doorWidth": 192,
            "doorHeight": 168, "doorCount": count, "panelColor": "WHITE",
            "panelDesign": "UDC", "trackRadius": "15", "trackThickness": "3",
            "trackMount": "bracket", "liftType": "standard", "hardware": dict(HW)}


FILL = [
    ("04-band-38k", "~$38k expect ~14%", big_tx450(9)),
    ("06-band-120k", "~$120k expect ~19%", big_tx450(28)),
    ("08-floor-180k", ">=$180k expect 22.65% floor", big_tx450(45)),
]

for label, intent, d in FILL:
    payload = {"doors": [d], "customerId": GNB_BC_ID,
               "poNumber": f"GNB-CURVE-TEST-{label.split('-')[0]}",
               "tagName": f"GNB CURVE TEST {label}", "deliveryType": "pickup"}
    r = requests.post(f"{API_BASE}/api/door-config/generate-quote", json=payload, timeout=300)
    if r.status_code != 200:
        print(f"[FAIL] {label}: HTTP {r.status_code} - {r.text[:200]}")
        continue
    data = r.json().get("data", r.json())
    esc = data.get("escalating_margin") or {}
    print(f"[OK] {label}: {data.get('bc_quote_number')} | sub=${(data.get('pricing') or {}).get('subtotal')} "
          f"| curve_sub=${esc.get('total_at_base_gm')} | GM={esc.get('target_gm')}% "
          f"| disc={esc.get('discount_pct')}% | lines={data.get('lines_added')}")
    time.sleep(1)
