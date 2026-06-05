#!/usr/bin/env python3
"""Create 10 GNB Doors (Manitoba) test quotes spanning the volume-margin curve.

Quotes are created in BC (prod) via the local backend on :8000. The escalating
volume curve only fires when AppSettings.pricing_enable_volume_curve is True in
whichever DB the backend uses — set it LOCALLY only for this test.

All quotes are tagged GNB-CURVE-TEST-NN for easy lookup / bulk delete after review.
"""
import json
import sys
import time

import requests

API_BASE = "http://localhost:8000"
GNB_BC_ID = "318ad8fb-4003-f011-9346-0022483d305e"  # GNB Doors (Manitoba)

HW_ALL = {
    "tracks": True, "springs": True, "struts": True, "hardwareKits": True,
    "weatherStripping": True, "bottomRetainer": True, "shafts": True,
}


def door(series, dtype, w, h, color, design, count=1, track="2", **extra):
    d = {
        "doorType": dtype, "doorSeries": series, "doorWidth": w, "doorHeight": h,
        "doorCount": count, "panelColor": color, "panelDesign": design,
        "trackRadius": "20" if series == "CRAFT" else "15", "trackThickness": track,
        "trackMount": "bracket", "liftType": "standard", "hardware": dict(HW_ALL),
    }
    d.update(extra)
    return d


# (label, intent, [door configs]) — doorCount sized to span the curve bands.
QUOTES = [
    ("01-below-threshold", "<$10k expect 0% discount",
     [door("TX450", "commercial", 108, 84, "WHITE", "UDC", count=1)]),

    ("02-band-10k", "~$10-12k expect ~5-7%",
     [door("KANATA", "residential", 192, 96, "WHITE", "SHXL", count=4)]),

    ("03-band-16k", "~$16-20k expect ~9-10%",
     [door("TX450", "commercial", 192, 168, "WHITE", "UDC", count=3, track="3")]),

    ("04-band-25k", "~$25-28k expect ~11%",
     [door("TX500", "commercial", 144, 120, "STEEL_GREY", "UDC", count=6, track="3")]),

    ("05-band-38k", "~$38-45k expect ~14%",
     [door("TX450", "commercial", 192, 168, "WHITE", "UDC", count=6, track="3")]),

    ("06-band-75k", "~$75k expect ~16.5%",
     [door("TX500-20", "commercial", 192, 144, "WHITE", "UDC", count=11, track="3")]),

    ("07-band-120k", "~$120k expect ~19%",
     [door("TX450", "commercial", 192, 168, "WHITE", "UDC", count=18, track="3")]),

    ("08-floor-180k", ">=$180k expect 22.65% floor",
     [door("TX500-20", "commercial", 192, 144, "WHITE", "UDC", count=28, track="3")]),

    ("09-alum-exclusion", "ALUM excluded; steel curve-priced",
     [door("AL976", "aluminium", 120, 96, "CLEAR_ANODIZED", "", count=3,
           glazingType="glass", glassPaneType="INSULATED", glassColor="CLEAR"),
      door("TX450", "commercial", 192, 168, "WHITE", "UDC", count=4, track="3")]),

    ("10-variety-mixed", "residential variety / woodgrain, mid band",
     [door("KANATA", "residential", 192, 96, "WALNUT", "BCXL", count=2),
      door("CRAFT", "residential", 144, 84, "WHITE", "FLUSH", count=2)]),
]


def main():
    results = []
    for label, intent, doors in QUOTES:
        payload = {
            "doors": doors,
            "customerId": GNB_BC_ID,
            "poNumber": f"GNB-CURVE-TEST-{label.split('-')[0]}",
            "tagName": f"GNB CURVE TEST {label}",
            "deliveryType": "pickup",  # avoid freight noise on the curve
        }
        try:
            r = requests.post(f"{API_BASE}/api/door-config/generate-quote",
                              json=payload, timeout=180)
        except Exception as e:
            print(f"[ERROR] {label}: {e}")
            results.append({"label": label, "intent": intent, "error": str(e)})
            continue

        if r.status_code != 200:
            print(f"[FAIL] {label}: HTTP {r.status_code} - {r.text[:300]}")
            results.append({"label": label, "intent": intent,
                            "http": r.status_code, "body": r.text[:300]})
            continue

        body = r.json()
        data = body.get("data", body)  # tolerate wrapped or flat
        esc = data.get("escalating_margin") or {}
        row = {
            "label": label,
            "intent": intent,
            "sq": data.get("bc_quote_number"),
            "bc_id": data.get("bc_quote_id"),
            "lines_added": data.get("lines_added"),
            "subtotal": (data.get("pricing") or {}).get("subtotal"),
            "total": (data.get("pricing") or {}).get("total"),
            "target_gm": esc.get("target_gm"),
            "discount_pct": esc.get("discount_pct"),
            "curve_subtotal": esc.get("total_at_base_gm"),
        }
        results.append(row)
        print(f"[OK] {label}: {row['sq']} | sub=${row['subtotal']} "
              f"| curve_sub=${row['curve_subtotal']} | GM={row['target_gm']}% "
              f"| disc={row['discount_pct']}% | lines={row['lines_added']}")
        time.sleep(1)

    with open("scripts/gnb_curve_test_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\n=== SUMMARY ===")
    for row in results:
        if row.get("sq"):
            print(f"  {row['label']:20s} {row['sq']:12s} "
                  f"sub=${row.get('subtotal')} disc={row.get('discount_pct')}%")
        else:
            print(f"  {row['label']:20s} FAILED: {row.get('error') or row.get('http')}")


if __name__ == "__main__":
    sys.exit(main())
