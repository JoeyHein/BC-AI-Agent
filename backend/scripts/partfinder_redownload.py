#!/usr/bin/env python3
"""Re-download quarantined (broken) PDFs in the DoorPart-Library corpus.

Reads the Part Finder quarantine list (or any CSV with rel_path/source_url),
fetches each from its source URL with a browser-like client, validates that
the result is a genuine, readable PDF (correct header, has %%EOF, opens with
pages in PyMuPDF), and only then writes it into the library — replacing the
truncated original. Failures are logged; the original is left untouched.

A companion URL file can supply source URLs for rows that lack one (the
manifest only covers part of the corpus). Format: CSV/TSV with columns
`rel_path,source_url` or `filename,source_url`.

Usage:
    # Re-download everything in quarantine.csv that has a source_url:
    python backend/scripts/partfinder_redownload.py

    # Supply discovered URLs for the rows missing one:
    python backend/scripts/partfinder_redownload.py --urls recovered_urls.csv

    # Dry run (show what would happen):
    python backend/scripts/partfinder_redownload.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.services.part_finder.config import IngestConfig  # noqa: E402

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def validate_pdf_bytes(data: bytes) -> tuple[bool, str]:
    """Genuine, readable PDF? Header + EOF + PyMuPDF opens with >=1 page."""
    if len(data) < 1024:
        return False, f"too-small({len(data)}B)"
    if b"%PDF" not in data[:1024]:
        return False, "not-pdf-header"
    if b"%%EOF" not in data[-2048:]:
        return False, "truncated-no-eof"
    try:
        import fitz

        d = fitz.open(stream=data, filetype="pdf")
        n = d.page_count
        d.close()
        if n < 1:
            return False, "zero-pages"
    except Exception as e:
        return False, f"unreadable:{type(e).__name__}"
    return True, f"ok({n}p)"


def load_url_overrides(path: Path) -> dict[str, str]:
    """Map rel_path or filename -> source_url from a discovered-URLs file."""
    overrides: dict[str, str] = {}
    if not path or not path.exists():
        return overrides
    text = path.read_text(encoding="utf-8")
    delim = "\t" if "\t" in text.splitlines()[0] else ","
    for row in csv.DictReader(text.splitlines(), delimiter=delim):
        url = (row.get("source_url") or row.get("url") or "").strip()
        if not url:
            continue
        for key in ("rel_path", "filename"):
            v = (row.get(key) or "").strip()
            if v:
                overrides[v] = url
    return overrides


def fetch(url: str, timeout: float = 45.0) -> tuple[bytes | None, str]:
    try:
        with httpx.Client(
            follow_redirects=True, timeout=timeout, headers=BROWSER_HEADERS, verify=True
        ) as client:
            r = client.get(url)
            if r.status_code != 200:
                return None, f"http-{r.status_code}"
            return r.content, "fetched"
    except Exception as e:
        return None, f"fetch-error:{type(e).__name__}"


def main() -> int:
    p = argparse.ArgumentParser(description="Re-download broken library PDFs.")
    p.add_argument("--quarantine", type=Path, help="quarantine.csv path")
    p.add_argument("--library", type=Path, help="DoorPart-Library root")
    p.add_argument("--urls", type=Path, help="CSV of discovered source URLs (rel_path/filename,source_url)")
    p.add_argument("--report", type=Path, help="Where to write the result CSV")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cfg = IngestConfig()
    if args.library:
        cfg.library_root = args.library
    quarantine = args.quarantine or cfg.quarantine_csv
    report_path = args.report or (cfg.output_dir / "redownload_report.csv")

    if not quarantine.exists():
        print(f"ERROR: quarantine file not found: {quarantine}", file=sys.stderr)
        return 2

    overrides = load_url_overrides(args.urls) if args.urls else {}
    rows = list(csv.DictReader(open(quarantine, encoding="utf-8")))

    results = []
    recovered = failed = skipped = 0
    print(f"{len(rows)} quarantined files | {len(overrides)} URL overrides supplied")
    print("-" * 70)

    for r in rows:
        rel = r["rel_path"]
        fn = r.get("filename") or Path(rel).name
        url = overrides.get(rel) or overrides.get(fn) or (r.get("source_url") or "").strip()
        dest = cfg.library_root / Path(rel)

        if not url:
            skipped += 1
            results.append({"rel_path": rel, "url": "", "status": "no-url"})
            print(f"  SKIP (no url)  {fn}")
            continue

        if args.dry_run:
            print(f"  WOULD FETCH    {fn}  <- {url}")
            results.append({"rel_path": rel, "url": url, "status": "dry-run"})
            continue

        data, fstat = fetch(url)
        if data is None:
            failed += 1
            results.append({"rel_path": rel, "url": url, "status": fstat})
            print(f"  FAIL  {fstat:24} {fn}")
            continue

        valid, vstat = validate_pdf_bytes(data)
        if not valid:
            failed += 1
            results.append({"rel_path": rel, "url": url, "status": f"invalid:{vstat}"})
            print(f"  FAIL  invalid:{vstat:16} {fn}")
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        recovered += 1
        results.append(
            {"rel_path": rel, "url": url, "status": f"recovered:{vstat}",
             "size_bytes": len(data), "sha256": sha}
        )
        print(f"  OK    {vstat:10} {len(data):>9}B  {fn}")
        time.sleep(0.3)  # be polite

    # Write report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rel_path", "url", "status", "size_bytes", "sha256"])
        w.writeheader()
        for row in results:
            w.writerow({k: row.get(k, "") for k in w.fieldnames})

    print("-" * 70)
    print(f"recovered={recovered}  failed={failed}  skipped(no-url)={skipped}")
    print(f"report -> {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
