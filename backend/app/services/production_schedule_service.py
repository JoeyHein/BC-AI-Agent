"""
Production schedule workbook — one row per in-flight BC sales order, with
Complete / Not Complete / blank(N/A) tracking columns for Panels, Hardware,
Tracks, Springs, Shafts, Weather Stripping, Operators.

Shop floor hand-edits the tracking columns directly in the live SharePoint
copy between refreshes. Every rebuild therefore reads back the current
SharePoint file FIRST, carries those edits forward keyed by SO number, then
overwrites the file in place — never a blind overwrite. SOs that drop out of
BC's open set move to an "Archived" sheet instead of being deleted, so
completed tracking history isn't lost.

Mirrors the read-back-before-overwrite pattern in planning_workbook_service.py.
"""

import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import CellIsRule
from openpyxl.utils import get_column_letter

from app.config import settings
from app.integrations.bc.client import bc_client
from app.integrations.email.client import graph_client

logger = logging.getLogger(__name__)

TRACKING_COLUMNS = [
    "Panels",
    "Hardware",
    "Tracks",
    "Springs",
    "Shafts",
    "Weather Stripping",
    "Operators",
]
HEADER = ["SO Number", "Customer Name", "Customer Tag / External Doc #"] + TRACKING_COLUMNS

NOT_COMPLETE = "Not Complete"
COMPLETE = "Complete"
NOT_APPLICABLE = ""  # blank dropdown entry — component not on this order

FIRST_TRACKING_COL = 4  # column D
LAST_TRACKING_COL = FIRST_TRACKING_COL + len(TRACKING_COLUMNS) - 1  # column J

RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
RED_FONT = Font(color="9C0006")
GREEN_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
GREEN_FONT = Font(color="006100")
WHITE_FILL = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
WHITE_FONT = Font(color="000000")
HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
ARCHIVED_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sort_key(so_number: str):
    digits = re.sub(r"\D", "", so_number or "")
    return int(digits) if digits else 0


def _normalize_status(value) -> str:
    if not value:
        return NOT_APPLICABLE
    value = str(value).strip()
    if value in (COMPLETE, NOT_COMPLETE):
        return value
    return NOT_COMPLETE


class ProductionScheduleService:

    # ── BC data ─────────────────────────────────────────────────────────

    def fetch_open_orders(self) -> List[Dict[str, Any]]:
        """All in-flight sales orders from BC.

        BC's salesOrders v2.0 entity only ever holds non-posted orders
        (posted = shipped/invoiced orders leave this entity entirely), so no
        status filter is needed to exclude completed work. Within that
        entity, "Draft" just means "not yet released for production" per
        bc_sync_service._map_bc_status_to_enum — it's still a real order
        that needs to be scheduled, so it must NOT be filtered out. Only an
        explicit Cancelled status is excluded.
        """
        cid = bc_client.company_id
        url = (
            f"{bc_client.base_url}/companies({cid})/salesOrders"
            f"?$select=id,number,customerName,externalDocumentNumber,status,orderDate"
        )
        orders = bc_client._paginate_v2(url, "in-flight sales orders (production schedule)")
        orders = [o for o in orders if "cancel" not in (o.get("status") or "").lower()]
        orders.sort(key=lambda o: _sort_key(o.get("number", "")))
        return orders

    # ── read-back ───────────────────────────────────────────────────────

    def parse_status_from_bytes(self, content: bytes) -> Dict[str, List[str]]:
        """Return {so_number: [status x7]} read from an existing workbook's
        Schedule + Archived sheets (bytes, e.g. downloaded from SharePoint)."""
        status_by_so: Dict[str, List[str]] = {}
        if not content:
            return status_by_so

        wb = load_workbook(io.BytesIO(content))
        for sheet_name in ("Schedule", "Archived"):
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or not row[0]:
                    continue
                so_number = str(row[0]).strip()
                statuses = list(row[FIRST_TRACKING_COL - 1:LAST_TRACKING_COL])
                statuses = [_normalize_status(s) for s in statuses]
                while len(statuses) < len(TRACKING_COLUMNS):
                    statuses.append(NOT_COMPLETE)
                status_by_so[so_number] = statuses
        return status_by_so

    # ── build ───────────────────────────────────────────────────────────

    def _style_sheet(self, ws, archived: bool = False):
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        for col_idx, title in enumerate(HEADER, start=1):
            cell = ws.cell(row=1, column=col_idx, value=title)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        widths = [14, 28, 26] + [14] * len(TRACKING_COLUMNS)
        for col_idx, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        ws.row_dimensions[1].height = 30

        max_row = max(ws.max_row, 2)
        for col_idx in range(FIRST_TRACKING_COL, LAST_TRACKING_COL + 1):
            col_letter = get_column_letter(col_idx)
            rng = f"{col_letter}2:{col_letter}{max_row}"

            if not archived:
                # Trailing comma adds a blank/N/A entry to the in-cell dropdown
                # list (component not on this order) alongside Complete/Not Complete.
                dv = DataValidation(type="list", formula1=f'"{COMPLETE},{NOT_COMPLETE},"', allow_blank=True)
                ws.add_data_validation(dv)
                dv.add(rng)

            ws.conditional_formatting.add(
                rng, CellIsRule(operator="equal", formula=[f'"{NOT_COMPLETE}"'], fill=RED_FILL, font=RED_FONT)
            )
            ws.conditional_formatting.add(
                rng, CellIsRule(operator="equal", formula=[f'"{COMPLETE}"'], fill=GREEN_FILL, font=GREEN_FONT)
            )
            ws.conditional_formatting.add(
                rng, CellIsRule(operator="equal", formula=['""'], fill=WHITE_FILL, font=WHITE_FONT)
            )

        for row in ws.iter_rows(min_row=2, max_row=max_row):
            for cell in row:
                cell.alignment = Alignment(horizontal="center") if cell.column >= FIRST_TRACKING_COL else Alignment(horizontal="left")
            if archived:
                for cell in row:
                    cell.fill = ARCHIVED_FILL

    def build_workbook_bytes(
        self, orders: List[Dict[str, Any]], status_by_so: Dict[str, List[str]]
    ) -> Tuple[bytes, int, int]:
        open_so_numbers = {o.get("number", "") for o in orders}

        wb = Workbook()
        ws = wb.active
        ws.title = "Schedule"

        for order in orders:
            so_number = order.get("number", "")
            statuses = status_by_so.get(so_number, [NOT_COMPLETE] * len(TRACKING_COLUMNS))
            row = [so_number, order.get("customerName", ""), order.get("externalDocumentNumber", "")] + statuses
            ws.append(row)

        self._style_sheet(ws)

        archived_so = sorted((so for so in status_by_so if so not in open_so_numbers), key=_sort_key)
        ws_archived = wb.create_sheet("Archived")
        for so_number in archived_so:
            ws_archived.append([so_number, "", ""] + status_by_so[so_number])
        self._style_sheet(ws_archived, archived=True)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), len(orders), len(archived_so)

    # ── orchestration ───────────────────────────────────────────────────

    def build_and_deliver(self) -> dict:
        """Download current SharePoint copy (if any), merge in fresh BC
        orders preserving hand-edited status, and overwrite the file in
        place. Requires PRODSCHED_SHAREPOINT_ENABLED + DRIVE_ID configured;
        raises if not (callers should check settings before calling in a
        context where that'd be unexpected, or use generate_local() instead).
        """
        if not (settings.PRODSCHED_SHAREPOINT_ENABLED and settings.PRODSCHED_SHAREPOINT_DRIVE_ID):
            raise RuntimeError("PRODSCHED_SHAREPOINT_ENABLED/DRIVE_ID not configured")

        status_by_so: Dict[str, List[str]] = {}
        try:
            current = graph_client.download_drive_file(
                settings.PRODSCHED_SHAREPOINT_DRIVE_ID,
                settings.PRODSCHED_SHAREPOINT_FILE_PATH,
            )
            if current:
                status_by_so = self.parse_status_from_bytes(current)
        except Exception as e:
            logger.error(f"[ProductionSchedule] SharePoint read-back failed: {e}")

        orders = self.fetch_open_orders()
        xlsx, open_count, archived_count = self.build_workbook_bytes(orders, status_by_so)

        sharepoint_url = graph_client.upload_drive_file(
            settings.PRODSCHED_SHAREPOINT_DRIVE_ID,
            settings.PRODSCHED_SHAREPOINT_FILE_PATH,
            xlsx,
        )
        result = {
            "open_orders": open_count,
            "archived_orders": archived_count,
            "sharepoint": sharepoint_url or settings.PRODSCHED_SHAREPOINT_WEB_URL or "uploaded",
        }
        logger.info(f"[ProductionSchedule] Refreshed: {result}")
        return result

    def generate_local(self, output_path) -> dict:
        """Local-file variant for manual/dev use — same merge semantics,
        reads and writes a filesystem path instead of SharePoint."""
        from pathlib import Path
        output_path = Path(output_path)

        status_by_so: Dict[str, List[str]] = {}
        if output_path.exists():
            status_by_so = self.parse_status_from_bytes(output_path.read_bytes())

        orders = self.fetch_open_orders()
        xlsx, open_count, archived_count = self.build_workbook_bytes(orders, status_by_so)
        output_path.write_bytes(xlsx)

        return {"open_orders": open_count, "archived_orders": archived_count, "path": str(output_path)}


production_schedule_service = ProductionScheduleService()
