"""Print each KPI for one month, with the Business Central documents behind it.

From the backend directory, with the app's environment loaded:

    python scripts/kpi_validation_report.py --month 2026-09

That calls Business Central. It is not the path the dashboard uses.

To print the documents saved with the nightly snapshot instead:

    python scripts/kpi_validation_report.py --month 2026-09 --snapshot
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.database import SessionLocal
from app.db.models import KpiSnapshot
from app.services.kpi_snapshot_service import format_as_of, month_window
from app.services.kpi_validation import format_validation_report


def report_for_month(month: str, *, snapshot: bool) -> str:
    window = month_window(month)
    db = SessionLocal()
    try:
        if snapshot:
            row = db.query(KpiSnapshot).filter(KpiSnapshot.month_key == window.month_key).one_or_none()
            if row is None or not row.trace:
                raise SystemExit(f"No stored trace for {window.month_key}. Run without --snapshot to read Business Central.")
            return format_validation_report(row.trace, month=window.label, as_of=format_as_of(row.generated_at))

        from app.services.kpi_dashboard_service import kpi_dashboard_service

        _payload, trace = kpi_dashboard_service.build_with_trace(db, window.start, window.end, today=window.end)
        return format_validation_report(trace, month=window.label, as_of="live read")
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check one month of KPIs against Business Central documents.")
    parser.add_argument("--month", required=True, help="Calendar month, YYYY-MM")
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Print the saved snapshot instead of calling Business Central",
    )
    args = parser.parse_args(argv)
    sys.stdout.write(report_for_month(args.month, snapshot=args.snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
