"""
Production schedule workbook — one row per in-flight BC sales order:
  SO Number | Customer Name | Customer Tag/External Doc # | Order Date |
  PO Date | Purchasing Status | Panels | Hardware | Tracks | Springs |
  Shafts | Weather Stripping | Operators | Shipping Status

Order Date is refreshed from BC every run. PO Date, Purchasing Status,
the 7 production tracking columns, and Shipping Status are all hand-edited
directly in the live SharePoint copy between refreshes (purchaser fills PO
Date + Purchasing Status; shop floor fills the production columns; shipping
fills Shipping Status).

Every rebuild reads back the current SharePoint file FIRST — by HEADER NAME,
not fixed column position, so the sheet can gain/reorder columns across
versions without corrupting older files on the next merge — and carries
those edits forward keyed by SO number, then overwrites the file in place.
SOs that drop out of BC's open set move to an "Archived" sheet (full row
snapshot, not just status) instead of being deleted, so history isn't lost.

Mirrors the read-back-before-overwrite pattern in planning_workbook_service.py.
"""

import io
import logging
import re
from datetime import date, datetime
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

NOT_COMPLETE = "Not Complete"
COMPLETE = "Complete"
NOT_APPLICABLE = ""  # blank dropdown entry — component not on this order

PURCHASING_STATES = ["Waiting to Order", "Ordered", "Shipped by Vendor", "Received"]
DEFAULT_PURCHASING_STATE = "Waiting to Order"

SHIPPING_STATES = ["Not Ready", "Ready to Ship", "Shipped"]
DEFAULT_SHIPPING_STATE = "Not Ready"

# Column layout (1-indexed) — also the header row's literal text, so
# read-back can locate columns by name instead of position.
COL_SO_NUMBER = 1
COL_CUSTOMER_NAME = 2
COL_CUSTOMER_TAG = 3
COL_ORDER_DATE = 4
COL_PO_DATE = 5
COL_PURCHASING_STATUS = 6
FIRST_TRACKING_COL = 7  # Panels
LAST_TRACKING_COL = FIRST_TRACKING_COL + len(TRACKING_COLUMNS) - 1  # Operators
COL_SHIPPING_STATUS = LAST_TRACKING_COL + 1

HEADER = (
    ["SO Number", "Customer Name", "Customer Tag / External Doc #", "Order Date", "PO Date", "Purchasing Status"]
    + TRACKING_COLUMNS
    + ["Shipping Status"]
)
assert len(HEADER) == COL_SHIPPING_STATUS

RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
RED_FONT = Font(color="9C0006")
GREEN_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
GREEN_FONT = Font(color="006100")
AMBER_FILL = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
AMBER_FONT = Font(color="9C6500")
BLUE_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
BLUE_FONT = Font(color="1F4E78")
WHITE_FILL = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
WHITE_FONT = Font(color="000000")
HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
ARCHIVED_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")

DATE_FORMAT = "mm/dd/yyyy"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sort_key(so_number: str):
    digits = re.sub(r"\D", "", so_number or "")
    return int(digits) if digits else 0


def _normalize_tracking_status(value) -> str:
    if not value:
        return NOT_APPLICABLE
    value = str(value).strip()
    if value in (COMPLETE, NOT_COMPLETE):
        return value
    return NOT_COMPLETE


def _normalize_choice(value, choices: List[str], default: str) -> str:
    value = (str(value).strip() if value else "")
    return value if value in choices else default


def _parse_date_value(value) -> Optional[date]:
    """Accept a datetime/date (openpyxl's native read for date-formatted
    cells) or an ISO-ish string (BC's orderDate, or hand-typed text)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


class _SORecord:
    """One sales order's full row state — fresh BC fields plus whatever's
    hand-edited. Used both for currently-open rows and for the Archived
    sheet snapshot of orders no longer open."""

    __slots__ = (
        "so_number", "customer_name", "customer_tag", "order_date",
        "po_date", "purchasing_status", "tracking", "shipping_status",
    )

    def __init__(self, so_number: str):
        self.so_number = so_number
        self.customer_name = ""
        self.customer_tag = ""
        self.order_date: Optional[date] = None
        self.po_date: Optional[date] = None
        self.purchasing_status = DEFAULT_PURCHASING_STATE
        self.tracking = [NOT_COMPLETE] * len(TRACKING_COLUMNS)
        self.shipping_status = DEFAULT_SHIPPING_STATE

    def to_row(self) -> list:
        return (
            [self.so_number, self.customer_name, self.customer_tag, self.order_date,
             self.po_date, self.purchasing_status]
            + self.tracking
            + [self.shipping_status]
        )


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

    def parse_records_from_bytes(self, content: bytes) -> Dict[str, _SORecord]:
        """Return {so_number: _SORecord} read from an existing workbook's
        Schedule + Archived sheets, keyed by HEADER NAME so older/newer
        sheet layouts don't get misread as the columns evolve."""
        records: Dict[str, _SORecord] = {}
        if not content:
            return records

        wb = load_workbook(io.BytesIO(content))
        for sheet_name in ("Schedule", "Archived"):
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
            col_by_name = {str(v).strip(): i for i, v in enumerate(header_row) if v}
            # SO Number is always column A regardless of schema version — fall
            # back to position 0 if the header text itself got clobbered (this
            # sheet previously had a bug where the header write could stomp a
            # data row, leaving a stray value in A1 instead of "SO Number").
            so_col_idx = col_by_name.get("SO Number", 0)

            def get(row, name):
                idx = col_by_name.get(name)
                return row[idx] if idx is not None and idx < len(row) else None

            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or so_col_idx >= len(row) or not row[so_col_idx]:
                    continue
                so_number = str(row[so_col_idx]).strip()
                rec = _SORecord(so_number)
                rec.customer_name = get(row, "Customer Name") or ""
                rec.customer_tag = get(row, "Customer Tag / External Doc #") or ""
                rec.order_date = _parse_date_value(get(row, "Order Date"))
                rec.po_date = _parse_date_value(get(row, "PO Date"))
                rec.purchasing_status = _normalize_choice(
                    get(row, "Purchasing Status"), PURCHASING_STATES, DEFAULT_PURCHASING_STATE
                )
                rec.tracking = [
                    _normalize_tracking_status(get(row, col)) for col in TRACKING_COLUMNS
                ]
                rec.shipping_status = _normalize_choice(
                    get(row, "Shipping Status"), SHIPPING_STATES, DEFAULT_SHIPPING_STATE
                )
                records[so_number] = rec
        return records

    # ── build ───────────────────────────────────────────────────────────

    def _style_sheet(self, ws, archived: bool = False):
        """Style an already-populated sheet. Row 1 must already hold the
        header (written via ws.append(HEADER) BEFORE any data rows) — this
        only applies fill/font, it never sets cell values. openpyxl's
        ws.append() fills from row 1 on a fresh sheet, so writing the header
        here-by-value after the data loop would silently clobber the first
        data row instead of pushing it down (a real bug this code used to
        have: the lowest-numbered open SO vanished from every single refresh)."""
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        for col_idx in range(1, len(HEADER) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        widths = [14, 28, 26, 13, 13, 17] + [14] * len(TRACKING_COLUMNS) + [15]
        for col_idx, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        ws.row_dimensions[1].height = 30

        max_row = max(ws.max_row, 2)

        for col_idx in (COL_ORDER_DATE, COL_PO_DATE):
            col_letter = get_column_letter(col_idx)
            for r in range(2, max_row + 1):
                ws.cell(row=r, column=col_idx).number_format = DATE_FORMAT

        def add_dropdown(col_idx, choices, allow_blank_entry=False):
            col_letter = get_column_letter(col_idx)
            rng = f"{col_letter}2:{col_letter}{max_row}"
            if not archived:
                options = list(choices) + [""] if allow_blank_entry else list(choices)
                dv = DataValidation(type="list", formula1=f'"{",".join(options)}"', allow_blank=True)
                ws.add_data_validation(dv)
                dv.add(rng)
            return rng

        # Purchasing Status: red -> amber -> blue -> green
        rng = add_dropdown(COL_PURCHASING_STATUS, PURCHASING_STATES)
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Waiting to Order"'], fill=RED_FILL, font=RED_FONT))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Ordered"'], fill=AMBER_FILL, font=AMBER_FONT))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Shipped by Vendor"'], fill=BLUE_FILL, font=BLUE_FONT))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Received"'], fill=GREEN_FILL, font=GREEN_FONT))

        # Production tracking columns: green / red / blank-white, with N/A dropdown entry
        for col_idx in range(FIRST_TRACKING_COL, LAST_TRACKING_COL + 1):
            rng = add_dropdown(col_idx, [COMPLETE, NOT_COMPLETE], allow_blank_entry=True)
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{NOT_COMPLETE}"'], fill=RED_FILL, font=RED_FONT))
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{COMPLETE}"'], fill=GREEN_FILL, font=GREEN_FONT))
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['""'], fill=WHITE_FILL, font=WHITE_FONT))

        # Shipping Status: red -> amber -> green
        rng = add_dropdown(COL_SHIPPING_STATUS, SHIPPING_STATES)
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Not Ready"'], fill=RED_FILL, font=RED_FONT))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Ready to Ship"'], fill=AMBER_FILL, font=AMBER_FONT))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Shipped"'], fill=GREEN_FILL, font=GREEN_FONT))

        for row in ws.iter_rows(min_row=2, max_row=max_row):
            for cell in row:
                cell.alignment = Alignment(horizontal="center") if cell.column >= COL_ORDER_DATE else Alignment(horizontal="left")
            if archived:
                for cell in row:
                    cell.fill = ARCHIVED_FILL

    def build_workbook_bytes(
        self, orders: List[Dict[str, Any]], records: Dict[str, _SORecord]
    ) -> Tuple[bytes, int, int]:
        open_so_numbers = {o.get("number", "") for o in orders}

        wb = Workbook()
        ws = wb.active
        ws.title = "Schedule"
        ws.append(HEADER)  # must be the first row appended — see _style_sheet docstring

        for order in orders:
            so_number = order.get("number", "")
            prior = records.get(so_number)
            rec = _SORecord(so_number) if prior is None else prior
            # Fresh-from-BC fields always win; hand-edited fields carry forward as-is.
            rec.customer_name = order.get("customerName", "")
            rec.customer_tag = order.get("externalDocumentNumber", "")
            rec.order_date = _parse_date_value(order.get("orderDate")) or rec.order_date
            ws.append(rec.to_row())

        self._style_sheet(ws)

        archived_so = sorted((so for so in records if so not in open_so_numbers), key=_sort_key)
        ws_archived = wb.create_sheet("Archived")
        ws_archived.append(HEADER)
        for so_number in archived_so:
            ws_archived.append(records[so_number].to_row())
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

        records: Dict[str, _SORecord] = {}
        try:
            current = graph_client.download_drive_file(
                settings.PRODSCHED_SHAREPOINT_DRIVE_ID,
                settings.PRODSCHED_SHAREPOINT_FILE_PATH,
            )
            if current:
                records = self.parse_records_from_bytes(current)
        except Exception as e:
            logger.error(f"[ProductionSchedule] SharePoint read-back failed: {e}")

        orders = self.fetch_open_orders()
        xlsx, open_count, archived_count = self.build_workbook_bytes(orders, records)

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

        records: Dict[str, _SORecord] = {}
        if output_path.exists():
            records = self.parse_records_from_bytes(output_path.read_bytes())

        orders = self.fetch_open_orders()
        xlsx, open_count, archived_count = self.build_workbook_bytes(orders, records)
        output_path.write_bytes(xlsx)

        return {"open_orders": open_count, "archived_orders": archived_count, "path": str(output_path)}


production_schedule_service = ProductionScheduleService()
