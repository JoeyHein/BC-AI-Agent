#!/usr/bin/env python3
"""One-off: download all iControls (icontrolsglobal.com) product PDFs into the
DoorPart-Library, validating each is a genuine complete PDF, and append rows to
the download manifest. Follows the corpus convention
{Brand}-{Series/Product}-{DocType}[-lang].pdf under
06-Garage-Door-Operators/North-America/iControls/.
"""

from __future__ import annotations

import csv
import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
import httpx

BASE = "https://www.icontrolsglobal.com/downloads/"
LIB = Path(os.environ.get("PARTFINDER_LIBRARY_ROOT", r"C:\Users\jhein\OneDrive\Open DC\DoorPart-Library"))
DEST = LIB / "06-Garage-Door-Operators" / "North-America" / "iControls"
MANIFEST = LIB / "_DOWNLOADS-LOG" / "manifest.csv"
CATEGORY, REGION, BRAND = "06-Garage-Door-Operators", "North-America", "iControls"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
}

# Source filenames (relative to BASE). Query strings preserved where needed.
SOURCES = [
    "pulse-100-series-operators-brochure.pdf",
    "pulse-100-series-operators-brochure-fr.pdf",
    "pulse-100-series-operators-brochure-es.pdf",
    "pulse-100-series-operators-installation-and-user-manual.pdf",
    "pulse-100-series-half-hp-size-50-gearbox-shop-drawing.pdf",
    "pulse-100-series-3-8ths-hp-size-50-gearbox-shop-drawing.pdf",
    "pulse-100-series-csi-spec.pdf",
    "pulse-200-series-operators-brochure.pdf",
    "pulse-200-series-operators-brochure-fr.pdf",
    "pulse-200-series-operators-brochure-es.pdf",
    "pulse-200-series-operators-installation-and-user-manual.pdf",
    "pulse-200-and-300-chain-hoist-installation-guide.pdf",
    "pulse-200-series-half-hp-size-50-gearbox-shop-drawing.pdf",
    "pulse-200-series-3-8ths-hp-size-50-gearbox-shop-drawing.pdf",
    "pulse-200-series-csi-spec.pdf",
    "pulse-300-series-operators-brochure.pdf",
    "pulse-300-series-operators-brochure-fr.pdf",
    "pulse-300-series-operators-brochure-es.pdf",
    "pulse-300-series-operators-installation-and-user-manual.pdf",
    "pulse-300-series-operators-installation-and-user-manual-fr.pdf",
    "pulse-300-series-half-hp-size-50-gearbox-shop-drawing.pdf",
    "pulse-300-series-half-hp-size-75-gearbox-shop-drawing.pdf",
    "pulse-300-series-3-4ths-hp-size-63-gearbox-shop-drawing.pdf",
    "pulse-300-series-3-4ths-hp-size-75-gearbox-shop-drawing.pdf",
    "pulse-300-series-1-hp-size-63-gearbox-shop-drawing.pdf",
    "pulse-300-series-1-hp-size-75-gearbox-shop-drawing.pdf",
    "pulse-300-series-csi-spec.pdf",
    "pulse-400-series-operators-brochure.pdf",
    "pulse-500-series-operators-brochure.pdf?v=2",
    "pulse-500-series-operators-brochure-fr.pdf?v=2",
    "pulse-500-series-operators-installation-and-user-manual.pdf",
    "pulse-residential-series-operators-brochure.pdf",
    "pulse-residential-series-operators-brochure-fr.pdf",
    "pulse-residential-series-operators-brochure-es.pdf",
    "pulse-200-residential-series-operators-installation-and-user-manual.pdf",
    "door-operator-accessories-brochure.pdf",
    "door-operator-accessories-brochure-fr.pdf",
    "door-operator-accessories-brochure-es.pdf",
    "led-stop-and-go-traffic-lights-brochure.pdf",
    "led-stop-and-go-traffic-lights-brochure-fr.pdf",
    "led-stop-and-go-traffic-lights-brochure-es.pdf",
    "tl24-led-stop-and-go-light-installation-guide.pdf",
    "tl96-led-stop-and-go-light-installation-guide.pdf",
    "led-guide-lights-brochure.pdf",
    "led-guide-lights-brochure-fr.pdf",
    "led-guide-lights-brochure-es.pdf",
    "gl24-led-guide-light-installation-guide.pdf",
    "communication-packages-brochure.pdf",
    "communication-packages-brochure-fr.pdf",
    "communication-packages-brochure-es.pdf",
    "tl96-led-light-communication-package-installation-guide.pdf",
    "control-panels-brochure.pdf",
    "control-panels-brochure-fr.pdf",
    "control-panels-brochure-es.pdf",
    "icontrols-warranty.pdf",
]

_ACRONYMS = {"hp": "HP", "led": "LED", "csi": "CSI", "tl24": "TL24", "tl96": "TL96",
             "gl24": "GL24", "com1": "COM1", "yl": "YL"}


def doc_type_of(stem: str) -> str:
    if "installation-and-user-manual" in stem:
        return "Install"
    if "installation-guide" in stem:
        return "Install-Guide"
    if "shop-drawing" in stem:
        return "ShopDrawing"
    if "csi-spec" in stem:
        return "Spec"
    if "warranty" in stem:
        return "Warranty"
    if "brochure" in stem:
        return "Brochure"
    return "Doc"


def target_name(src: str) -> str:
    stem = src.split("?", 1)[0][:-4]  # strip query + .pdf
    lang = ""
    for suf, tag in (("-fr", "-FR"), ("-es", "-ES")):
        if stem.endswith(suf):
            stem, lang = stem[: -len(suf)], tag
            break
    stem = stem.replace("installation-and-user-manual", "Install")
    stem = stem.replace("installation-guide", "Install-Guide")
    stem = stem.replace("shop-drawing", "ShopDrawing")
    stem = stem.replace("csi-spec", "Spec")
    stem = stem.replace("operators-", "").replace("-operators", "")
    stem = stem.replace("icontrols-", "")  # avoid double brand prefix on warranty
    parts = []
    for p in stem.split("-"):
        parts.append(_ACRONYMS.get(p.lower(), p[:1].upper() + p[1:] if p else p))
    return "iControls-" + "-".join(parts) + lang + ".pdf"


def validate(data: bytes) -> tuple[bool, str]:
    if len(data) < 1024:
        return False, f"too-small({len(data)})"
    if b"%PDF" not in data[:1024]:
        return False, "not-pdf-header"
    if b"%%EOF" not in data[-2048:]:
        return False, "truncated-no-eof"
    try:
        d = fitz.open(stream=data, filetype="pdf")
        n = d.page_count
        d.close()
        if n < 1:
            return False, "zero-pages"
    except Exception as e:
        return False, f"unreadable:{type(e).__name__}"
    return True, f"ok({n}p)"


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    rows = []
    ok = fail = 0
    print(f"Downloading {len(SOURCES)} iControls PDFs -> {DEST}")
    print("-" * 70)
    with httpx.Client(follow_redirects=True, timeout=60, headers=HEADERS) as client:
        for src in SOURCES:
            url = BASE + src
            name = target_name(src)
            try:
                r = client.get(url)
                if r.status_code != 200:
                    print(f"  FAIL http-{r.status_code:<14} {src}")
                    fail += 1
                    continue
                data = r.content
                valid, vstat = validate(data)
                if not valid:
                    print(f"  FAIL {vstat:<18} {src}")
                    fail += 1
                    continue
                (DEST / name).write_bytes(data)
                sha = hashlib.sha256(data).hexdigest()
                rows.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "category": CATEGORY, "region": REGION, "brand": BRAND,
                    "doc_type": doc_type_of(src.split("?", 1)[0][:-4]),
                    "filename": name, "source_url": url,
                    "size_bytes": len(data), "sha256": sha, "status": "OK",
                })
                print(f"  OK   {vstat:<10} {len(data):>9}B  {name}")
                ok += 1
                time.sleep(0.25)
            except Exception as e:
                print(f"  FAIL {type(e).__name__:<18} {src}")
                fail += 1

    # Append to manifest (never rewrite).
    if rows:
        cols = ["timestamp", "category", "region", "brand", "doc_type",
                "filename", "source_url", "size_bytes", "sha256", "status"]
        with open(MANIFEST, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            for row in rows:
                w.writerow(row)

    print("-" * 70)
    print(f"recovered={ok}  failed={fail}  -> manifest += {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
