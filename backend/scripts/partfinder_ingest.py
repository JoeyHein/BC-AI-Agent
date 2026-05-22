#!/usr/bin/env python3
"""CLI to build the Part Finder index from the DoorPart-Library corpus.

Examples:
    # Full ingest with defaults (library + output from config/env):
    python backend/scripts/partfinder_ingest.py

    # Smoke test on 15 PDFs:
    python backend/scripts/partfinder_ingest.py --limit 15

    # Custom paths, no cover rendering (fastest text-only pass):
    python backend/scripts/partfinder_ingest.py \
        --library "D:/DoorPart-Library" --out "D:/pf-index" --no-covers
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the backend package importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.part_finder.config import IngestConfig  # noqa: E402
from app.services.part_finder.ingest import run_ingest  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Build the Part Finder index.")
    p.add_argument("--library", type=Path, help="DoorPart-Library root")
    p.add_argument("--out", type=Path, help="Output directory for index artifacts")
    p.add_argument("--limit", type=int, default=0, help="Process only N PDFs (smoke test)")
    p.add_argument("--no-covers", action="store_true", help="Skip cover thumbnail rendering")
    p.add_argument("--cover-px", type=int, default=1024, help="Cover thumbnail long edge (px)")
    p.add_argument("--quiet", action="store_true", help="Less progress output")
    args = p.parse_args()

    cfg = IngestConfig()
    if args.library:
        cfg.library_root = args.library
    if args.out:
        cfg.output_dir = args.out
    cfg.limit = args.limit
    cfg.render_covers = not args.no_covers
    cfg.cover_long_edge_px = args.cover_px

    if not cfg.library_root.exists():
        print(f"ERROR: library root not found: {cfg.library_root}", file=sys.stderr)
        return 2

    print(f"Library : {cfg.library_root}")
    print(f"Output  : {cfg.output_dir}")
    print(f"Covers  : {cfg.render_covers}  Limit: {cfg.limit or 'all'}")
    print("-" * 60)

    stats = run_ingest(cfg, fresh=True, verbose=not args.quiet)

    print("-" * 60)
    print(f"DONE in {stats['elapsed_sec']}s")
    print(f"  documents ok      : {stats['docs_ok']}")
    print(f"  documents broken  : {stats['docs_broken']}  -> {Path(stats['quarantine_csv']).name}")
    print(f"  documents scanned : {stats['docs_scanned']}")
    print(f"  pages indexed     : {stats['pages']}")
    print(f"  part-number tokens: {stats['part_numbers_unique_doc_tokens']}")
    print(f"  pages needing OCR : {stats['needs_ocr_pages']}")
    print(f"  index db          : {cfg.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
