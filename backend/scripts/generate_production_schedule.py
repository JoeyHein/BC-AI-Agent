"""
Generate / refresh the production schedule workbook from open BC sales orders.

Usage:
    python scripts/generate_production_schedule.py            # SharePoint if
                                                                # configured, else local
    python scripts/generate_production_schedule.py --local [path]   # force local file
    python scripts/generate_production_schedule.py --sharepoint     # force SharePoint

Behavior (see app/services/production_schedule_service.py for the real logic):
- Pulls every in-flight sales order from Business Central.
- Reads back whatever copy already exists (SharePoint or local file) and
  carries forward hand-edited status per SO number — never a blind overwrite.
- Each tracking column (Panels..Operators) is a dropdown: Complete (green) /
  Not Complete (red) / blank (white, N/A — component not on this order).
- SOs no longer open in BC move to an "Archived" sheet instead of vanishing.
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from app.config import settings
from app.services.production_schedule_service import production_schedule_service

DEFAULT_LOCAL_PATH = Path(__file__).resolve().parent / "production_schedule.xlsx"


def main():
    args = sys.argv[1:]
    force_local = "--local" in args
    force_sharepoint = "--sharepoint" in args
    positional = [a for a in args if not a.startswith("--")]

    use_sharepoint = settings.PRODSCHED_SHAREPOINT_ENABLED and settings.PRODSCHED_SHAREPOINT_DRIVE_ID
    if force_sharepoint:
        use_sharepoint = True
    if force_local:
        use_sharepoint = False

    if use_sharepoint:
        print(f"Refreshing SharePoint copy: {settings.PRODSCHED_SHAREPOINT_FILE_PATH}")
        result = production_schedule_service.build_and_deliver()
        print(f"  Open SOs: {result['open_orders']}")
        print(f"  Archived: {result['archived_orders']}")
        print(f"  Production orders: {result['production_orders']} ({result['assigned']} assigned)")
        print(f"  SharePoint: {result['sharepoint']}")
    else:
        output_path = Path(positional[0]) if positional else DEFAULT_LOCAL_PATH
        print(f"Refreshing local file: {output_path}")
        result = production_schedule_service.generate_local(output_path)
        print(f"  Open SOs: {result['open_orders']}")
        print(f"  Archived: {result['archived_orders']}")
        print(f"  Production orders: {result['production_orders']} ({result['assigned']} assigned)")
        print(f"  Saved: {result['path']}")


if __name__ == "__main__":
    main()
