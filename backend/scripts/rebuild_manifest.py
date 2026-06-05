#!/usr/bin/env python3
"""Rebuild the download manifest from on-disk reality + reconstructable source
URLs. Produces a COMPLETE manifest covering every PDF actually in the library
(the historical manifest was always partial). Source URLs are recovered for:
  - wave-N harvest CSVs (data/partfinder/harvest/*.csv)
  - iControls (recomputed from fetch_icontrols.SOURCES)
  - any surviving rows in the current manifest (matched by filename)
Files with no recoverable URL get a blank source_url (the file + folder-derived
brand/category/region/sha/size are still recorded).

Backs up the existing manifest before writing.
"""

from __future__ import annotations

import csv
import hashlib
import os
import sys
from datetime import datetime, timezone
from glob import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_brand_manuals import derive_filename, safe_component  # noqa: E402

LIB = Path(os.environ.get("PARTFINDER_LIBRARY_ROOT", r"C:\Users\jhein\OneDrive\Open DC\DoorPart-Library"))
MAN = LIB / "_DOWNLOADS-LOG" / "manifest.csv"
HARVEST = Path(__file__).resolve().parents[1] / "data" / "partfinder" / "harvest"
META = {"_INDEX", "_DOWNLOADS-LOG", "_PLAYBOOK"}
COLS = ["timestamp", "category", "region", "brand", "doc_type",
        "filename", "source_url", "size_bytes", "sha256", "status"]


def read_csv_resilient(path: Path) -> list[dict]:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    return []


def build_url_map() -> dict[str, dict]:
    """final_filename -> {source_url, doc_type} from harvest CSVs + iControls."""
    m: dict[str, dict] = {}
    # Wave harvest CSVs: recompute the final on-disk filename the downloader used.
    for p in sorted(glob(str(HARVEST / "*.csv"))):
        for r in read_csv_resilient(Path(p)):
            url = (r.get("source_url") or "").strip()
            brand = (r.get("brand") or "").strip()
            if not url or not brand:
                continue
            fname = derive_filename(brand, url, (r.get("filename") or "").strip())
            m.setdefault(fname, {"source_url": url, "doc_type": (r.get("doc_type") or "").strip()})
    # iControls (recompute).
    try:
        import fetch_icontrols as ic
        for src in ic.SOURCES:
            fname = ic.target_name(src)
            m.setdefault(fname, {"source_url": ic.BASE + src,
                                 "doc_type": ic.doc_type_of(src.split("?", 1)[0][:-4])})
    except Exception as e:
        print("  (iControls map skipped:", e, ")")
    return m


def surviving_rows() -> dict[str, dict]:
    """filename -> row dict from the current (possibly truncated) manifest."""
    out = {}
    if MAN.exists():
        for r in read_csv_resilient(MAN):
            fn = (r.get("filename") or "").strip()
            if fn:
                out[fn] = r
    return out


def main() -> int:
    url_map = build_url_map()
    survivors = surviving_rows()
    print(f"recoverable URLs: {len(url_map)} (harvest+iControls) | surviving manifest rows: {len(survivors)}")

    if MAN.exists():
        bak = MAN.with_suffix(".csv.truncated.bak")
        bak.write_bytes(MAN.read_bytes())
        print(f"backed up current manifest -> {bak.name}")

    rows = []
    have_url = no_url = 0
    for pdf in sorted(LIB.rglob("*.pdf")):
        rel = pdf.relative_to(LIB)
        if any(part in META for part in rel.parts):
            continue
        parts = rel.parts
        category = parts[0] if len(parts) > 0 else ""
        region = parts[1] if len(parts) > 1 else ""
        brand = parts[2] if len(parts) > 3 else ""
        fname = pdf.name
        try:
            data = pdf.read_bytes()
        except OSError:
            continue
        sha = hashlib.sha256(data).hexdigest()
        info = url_map.get(fname)
        src_row = survivors.get(fname)
        source_url = (info or {}).get("source_url") or (src_row or {}).get("source_url", "") or ""
        doc_type = (info or {}).get("doc_type") or (src_row or {}).get("doc_type", "") or ""
        ts = (src_row or {}).get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows.append({
            "timestamp": ts, "category": category, "region": region, "brand": brand,
            "doc_type": doc_type or "Doc", "filename": fname, "source_url": source_url,
            "size_bytes": len(data), "sha256": sha, "status": "OK",
        })
        if source_url:
            have_url += 1
        else:
            no_url += 1

    with open(MAN, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)

    print(f"rebuilt manifest: {len(rows)} rows | with source_url: {have_url} | without: {no_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
