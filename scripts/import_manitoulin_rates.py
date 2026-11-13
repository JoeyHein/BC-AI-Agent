#!/usr/bin/env python3
"""Fill the Manitoulin agreement #19067426 rate JSON from the workbook.

The workbook is not in the repo. On the box it is named
``/workspace/freight/190674sa26 (1).xlsx``. This script reads that file
(or any path you pass) and writes backend/data/freight/manitoulin_rates.json.

Layouts it understands:

- Stacked: a row that names the origin (Redcliff, Milton, or Mississauga),
  then a header row with MIN, L5C (or <500), 500, 1000, 2000, 5000, 10000,
  20000, then one destination per row.
- Flat: columns Origin, Destination, MIN, L5C, 500, 1000, 2000, 5000,
  10000, 20000.
- Side by side: the same break headers repeated, with the origin named in
  the row above each group.

Cells the sheet does not contain stay null. A null cell is not $0.

    python scripts/import_manitoulin_rates.py --inspect "/path/to/190674sa26 (1).xlsx"
    python scripts/import_manitoulin_rates.py "/path/to/190674sa26 (1).xlsx"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.manitoulin_rate_table import (  # noqa: E402
    DATA_PATH,
    apply_extracted,
    extract_lanes_from_workbook,
    inspect_workbook,
    placeholder_document,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", help="Path to the Manitoulin preferential workbook (.xlsx)")
    parser.add_argument("--out", default=str(DATA_PATH), help="Rate JSON to write")
    parser.add_argument("--inspect", action="store_true", help="Print the sheet grid and do not write")
    args = parser.parse_args(argv)
    path = Path(args.workbook)
    if not path.exists():
        print(f"Workbook not found: {path}", file=sys.stderr)
        print("The rate file shipped with the repo stays a placeholder until this file is available.", file=sys.stderr)
        return 1
    if args.inspect:
        print(inspect_workbook(str(path)))
        return 0
    extracted = extract_lanes_from_workbook(str(path))
    if not extracted:
        print("No lanes were recognized.", file=sys.stderr)
        print(inspect_workbook(str(path)))
        print("If the grid above does not match a documented layout, send the header row.", file=sys.stderr)
        return 2
    document = apply_extracted(placeholder_document(), extracted, path.name)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")
    filled = sum(
        (1 if lane.get("min") is not None else 0) + sum(1 for value in lane["rates"].values() if value is not None)
        for lane in document["lanes"]
    )
    print(f"Wrote {out} with {filled} filled cells from {len(extracted)} lanes ({document['status']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
