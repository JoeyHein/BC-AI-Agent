#!/usr/bin/env python3
"""Reusable brand-manual harvester for the DoorPart-Library.

Reads one or more "harvest list" CSVs (produced by discovery agents) and, for
each row, downloads the PDF, validates it is a genuine complete PDF, dedupes by
content hash (against the existing manifest AND within the run), names it to the
library convention, saves it under {category}/{region}/{brand}/, and appends a
row to the download manifest.

Harvest CSV columns (header required):
    brand, source_url            (required)
    category, region, doc_type, filename   (optional — sensible fallbacks)

Usage:
    # Download everything in the harvest dir:
    python scripts/fetch_brand_manuals.py

    # Specific files / dry run:
    python scripts/fetch_brand_manuals.py --harvest data/partfinder/harvest/liftmaster.csv
    python scripts/fetch_brand_manuals.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from glob import glob
from pathlib import Path

import fitz  # PyMuPDF
import httpx

LIB = Path(os.environ.get("PARTFINDER_LIBRARY_ROOT", r"C:\Users\jhein\OneDrive\Open DC\DoorPart-Library"))
MANIFEST = LIB / "_DOWNLOADS-LOG" / "manifest.csv"
DEFAULT_HARVEST_DIR = Path(__file__).resolve().parents[1] / "data" / "partfinder" / "harvest"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

MANIFEST_COLS = ["timestamp", "category", "region", "brand", "doc_type",
                 "filename", "source_url", "size_bytes", "sha256", "status"]

# Map manufacturers-CSV-style category prefixes to library folder names.
CATEGORY_FOLDERS = {
    "01": "01-Garage-Door-Panels", "02": "02-Garage-Door-Hardware",
    "03": "03-Garage-Door-Springs", "04": "04-Dock-Equipment",
    "05": "05-Dock-Seals-Shelters", "06": "06-Garage-Door-Operators",
}
VALID_CATEGORIES = set(CATEGORY_FOLDERS.values())
VALID_REGIONS = {"North-America", "Europe", "Asia-Pacific", "Latin-America", "Other"}


def norm_category(raw: str) -> str:
    raw = (raw or "").strip()
    if raw in VALID_CATEGORIES:
        return raw
    if raw[:2] in CATEGORY_FOLDERS:
        return CATEGORY_FOLDERS[raw[:2]]
    return "06-Garage-Door-Operators"  # fallback; most harvest targets are operators


def safe_component(s: str) -> str:
    # Transliterate accents to ASCII first (Hörmann -> Hormann) so brand folders
    # match the corpus's ASCII naming and don't fragment.
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s.strip())
    return re.sub(r"-{2,}", "-", s).strip("-")


def derive_filename(brand: str, url: str, given: str) -> str:
    if given and given.strip():
        name = safe_component(given.strip())
    else:
        base = url.split("?", 1)[0].rstrip("/").split("/")[-1]
        base = base[:-4] if base.lower().endswith(".pdf") else base
        name = safe_component(base) or "document"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    brand_tok = safe_component(brand)
    if brand_tok and not name.lower().startswith(brand_tok.lower()):
        name = f"{brand_tok}-{name}"
    return name


def validate(data: bytes) -> tuple[bool, str, int]:
    if len(data) < 1024:
        return False, f"too-small({len(data)})", 0
    if b"%PDF" not in data[:1024]:
        return False, "not-pdf-header", 0
    if b"%%EOF" not in data[-2048:]:
        return False, "truncated-no-eof", 0
    try:
        d = fitz.open(stream=data, filetype="pdf")
        n = d.page_count
        d.close()
        if n < 1:
            return False, "zero-pages", 0
    except Exception as e:
        return False, f"unreadable:{type(e).__name__}", 0
    return True, f"ok({n}p)", n


def load_known_shas() -> set[str]:
    """Content hashes already in the library — from the manifest AND by hashing
    every PDF actually on disk (the manifest is incomplete, e.g. re-downloaded
    files were never recorded), so content-dedup is reliable."""
    shas: set[str] = set()
    if MANIFEST.exists():
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with open(MANIFEST, encoding=enc, newline="") as f:
                    for row in csv.DictReader(f):
                        s = (row.get("sha256") or "").strip()
                        if s:
                            shas.add(s)
                break
            except UnicodeDecodeError:
                continue
    # Hash on-disk PDFs (skip meta folders).
    n = 0
    for p in LIB.rglob("*.pdf"):
        if any(part.startswith("_") for part in p.relative_to(LIB).parts):
            continue
        try:
            shas.add(hashlib.sha256(p.read_bytes()).hexdigest())
            n += 1
        except OSError:
            pass
    print(f"  (deduped against {n} on-disk PDFs + manifest)")
    return shas


def read_harvest_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for p in paths:
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with open(p, encoding=enc, newline="") as f:
                    for r in csv.DictReader(f):
                        url = (r.get("source_url") or r.get("url") or "").strip()
                        brand = (r.get("brand") or "").strip()
                        if url and brand:
                            rows.append({
                                "brand": brand, "source_url": url,
                                "category": (r.get("category") or "").strip(),
                                "region": (r.get("region") or "").strip(),
                                "doc_type": (r.get("doc_type") or "").strip(),
                                "filename": (r.get("filename") or "").strip(),
                                "_src": p.name,
                            })
                break
            except UnicodeDecodeError:
                continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Harvest brand manuals into the library.")
    ap.add_argument("--harvest", action="append", help="harvest CSV (repeatable); default: all in harvest dir")
    ap.add_argument("--harvest-dir", type=Path, default=DEFAULT_HARVEST_DIR)
    ap.add_argument("--library", type=Path, help="override library root")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    global LIB, MANIFEST
    if args.library:
        LIB = args.library
        MANIFEST = LIB / "_DOWNLOADS-LOG" / "manifest.csv"

    paths = [Path(h) for h in args.harvest] if args.harvest else \
        sorted(Path(p) for p in glob(str(args.harvest_dir / "*.csv")))
    if not paths:
        print(f"No harvest CSVs found in {args.harvest_dir}", file=sys.stderr)
        return 2

    rows = read_harvest_rows(paths)
    # De-dupe rows by URL up front.
    seen_urls, unique = set(), []
    for r in rows:
        if r["source_url"] not in seen_urls:
            seen_urls.add(r["source_url"])
            unique.append(r)
    if args.limit:
        unique = unique[: args.limit]

    known_shas = load_known_shas()
    print(f"harvest files: {len(paths)} | rows: {len(rows)} | unique URLs: {len(unique)} | "
          f"known shas: {len(known_shas)} | mode: {'DRY-RUN' if args.dry_run else 'DOWNLOAD'}")
    print("-" * 76)

    run_shas: set[str] = set()
    manifest_rows = []
    per_brand: dict[str, int] = {}
    ok = dup = fail = 0

    insecure = httpx.Client(follow_redirects=True, timeout=60, headers=HEADERS, verify=False)
    with httpx.Client(follow_redirects=True, timeout=60, headers=HEADERS) as client:
        for r in unique:
            brand, url = r["brand"], r["source_url"]
            # Resolve the destination first so we can skip already-saved files
            # WITHOUT re-fetching — makes the harvester idempotent / resumable.
            category = norm_category(r["category"])
            region = r["region"] if r["region"] in VALID_REGIONS else "North-America"
            fname = derive_filename(brand, url, r["filename"])
            dest = LIB / category / region / safe_component(brand) / fname
            if dest.exists():
                dup += 1
                continue
            try:
                try:
                    resp = client.get(url)
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    # Retry hosts with incomplete TLS chains (e.g. Garaga/NWD CDNs).
                    resp = insecure.get(url)
                if resp.status_code != 200:
                    print(f"  FAIL http-{resp.status_code:<12} {brand} <- {url[:70]}")
                    fail += 1
                    continue
                data = resp.content
                valid, vstat, _ = validate(data)
                if not valid:
                    print(f"  FAIL {vstat:<16} {brand} <- {url[:70]}")
                    fail += 1
                    continue
                sha = hashlib.sha256(data).hexdigest()
                if sha in known_shas or sha in run_shas:
                    dup += 1
                    print(f"  DUP  {brand:<16} (content already in library)")
                    continue

                run_shas.add(sha)
                if args.dry_run:
                    print(f"  WOULD {vstat:<9} {brand:<16} {category}/{region} {fname}")
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                manifest_rows.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "category": category, "region": region, "brand": brand,
                    "doc_type": r["doc_type"] or "Doc", "filename": fname,
                    "source_url": url, "size_bytes": len(data), "sha256": sha, "status": "OK",
                })
                per_brand[brand] = per_brand.get(brand, 0) + 1
                ok += 1
                print(f"  OK   {vstat:<9} {len(data):>9}B  {brand:<16} {fname}")
                time.sleep(0.2)
            except Exception as e:
                print(f"  FAIL {type(e).__name__:<16} {brand} <- {url[:60]}")
                fail += 1

    if manifest_rows and not args.dry_run:
        with open(MANIFEST, "a", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=MANIFEST_COLS).writerows(manifest_rows)

    print("-" * 76)
    print(f"downloaded={ok}  duplicates_skipped={dup}  failed={fail}")
    if per_brand:
        print("per brand:", ", ".join(f"{b}={n}" for b, n in sorted(per_brand.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
