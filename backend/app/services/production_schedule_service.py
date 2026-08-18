"""
Production schedule workbook — one row per in-flight BC sales order, with a
two-row grouped header:

  SO Number | Customer Name | Customer Tag/External Doc # | Order Date |
  PO Date | [Panels: Purchasing|Production] | [Hardware: Purchasing|Production]
  | [Tracks: ...] | [Springs: ...] | [Shafts: ...] | [Weather Stripping: ...]
  | [Operators: ...] | Shipping Status

Each of the 7 components gets its own Purchasing Status (Waiting to
Order/Ordered/Shipped by Vendor/In Stock/Received) AND Production status
(Complete/Not Complete/blank-N/A) — components are purchased and built
independently, so e.g. Panels can be "Shipped by Vendor" while Hardware is
"In Stock" on the same order.

Order Date is refreshed from BC every run. Everything else (PO Date, the 14
per-component status columns, Shipping Status) is hand-edited directly in
the live SharePoint copy between refreshes.

Every rebuild reads back the current SharePoint file FIRST and carries edits
forward keyed by SO number, then overwrites the file in place. Schedule/
Archived read-back auto-detects the sheet's header generation (this 2-row
layout, or either of the two earlier 1-row layouts) so upgrading the schema
never loses data already sitting in the live file — see
parse_records_from_bytes. SOs that drop out of BC's open set move to an
"Archived" sheet (full row snapshot) instead of being deleted.

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

PURCHASING_STATES = ["Waiting to Order", "Ordered", "Shipped by Vendor", "In Stock", "Received"]
DEFAULT_PURCHASING_STATE = "Waiting to Order"

SHIPPING_STATES = ["Not Ready", "Ready to Ship", "Shipped"]
DEFAULT_SHIPPING_STATE = "Not Ready"

# ── column layout (1-indexed) ───────────────────────────────────────────
COL_SO_NUMBER = 1
COL_CUSTOMER_NAME = 2
COL_CUSTOMER_TAG = 3
COL_ORDER_DATE = 4
COL_PO_DATE = 5
FIRST_COMPONENT_COL = 6  # Panels Purchasing starts here; each component = 2 cols

def _purchasing_col(component_idx: int) -> int:
    return FIRST_COMPONENT_COL + component_idx * 2

def _production_col(component_idx: int) -> int:
    return _purchasing_col(component_idx) + 1

COL_SHIPPING_STATUS = FIRST_COMPONENT_COL + len(TRACKING_COLUMNS) * 2  # 20
TOTAL_COLUMNS = COL_SHIPPING_STATUS

DATA_START_ROW_V3 = 3   # two header rows
DATA_START_ROW_LEGACY = 2  # one header row (older schema versions)

RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
RED_FONT = Font(color="9C0006")
GREEN_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
GREEN_FONT = Font(color="006100")
AMBER_FILL = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
AMBER_FONT = Font(color="9C6500")
BLUE_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
BLUE_FONT = Font(color="1F4E78")
PURPLE_FILL = PatternFill(start_color="E4DFEC", end_color="E4DFEC", fill_type="solid")
PURPLE_FONT = Font(color="60497A")
WHITE_FILL = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
WHITE_FONT = Font(color="000000")
HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
SUBHEADER_FILL = PatternFill(start_color="2E6DA4", end_color="2E6DA4", fill_type="solid")
ARCHIVED_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")

DATE_FORMAT = "mm/dd/yyyy"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Legacy (pre-this-version) single-row-header field names, needed to migrate
# older live files without losing their data. See parse_records_from_bytes.
LEGACY_SHARED_PURCHASING_STATUS = "Purchasing Status"


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
        "so_number", "customer_name", "customer_tag", "order_date", "po_date",
        "purchasing", "production", "shipping_status",
    )

    def __init__(self, so_number: str):
        self.so_number = so_number
        self.customer_name = ""
        self.customer_tag = ""
        self.order_date: Optional[date] = None
        self.po_date: Optional[date] = None
        self.purchasing: Dict[str, str] = {c: DEFAULT_PURCHASING_STATE for c in TRACKING_COLUMNS}
        self.production: Dict[str, str] = {c: NOT_COMPLETE for c in TRACKING_COLUMNS}
        self.shipping_status = DEFAULT_SHIPPING_STATE

    def to_row(self) -> list:
        row = [self.so_number, self.customer_name, self.customer_tag, self.order_date, self.po_date]
        for c in TRACKING_COLUMNS:
            row.append(self.purchasing[c])
            row.append(self.production[c])
        row.append(self.shipping_status)
        return row


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
        Schedule + Archived sheets. Auto-detects which header generation the
        sheet uses so upgrading the schema never loses data already sitting
        in the live file:

        - v3 (this version): 2 header rows, per-component Purchasing/
          Production column pairs. Detected by "Purchasing"/"Production"
          literals appearing in row 2. Read positionally (the layout is
          fully known once detected).
        - legacy (either earlier 1-row-header version — a single shared
          "Purchasing Status" column, or no purchasing tracking at all):
          read by HEADER NAME instead of position, since those versions'
          columns don't line up with each other either. The single shared
          Purchasing Status value (if present) seeds ALL 7 components,
          since that's the best available signal for what used to be one
          combined field.
        """
        records: Dict[str, _SORecord] = {}
        if not content:
            return records

        wb = load_workbook(io.BytesIO(content))
        for sheet_name in ("Schedule", "Archived"):
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            row1 = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
            row2 = next(ws.iter_rows(min_row=2, max_row=2, values_only=True), ())
            is_v3 = any(str(v).strip() in ("Purchasing", "Production") for v in row2 if v)

            if is_v3:
                self._parse_v3_sheet(ws, records)
            else:
                self._parse_legacy_sheet(ws, row1, records)
        return records

    def _parse_v3_sheet(self, ws, records: Dict[str, _SORecord]):
        for row in ws.iter_rows(min_row=DATA_START_ROW_V3, values_only=True):
            if not row or len(row) < TOTAL_COLUMNS or not row[COL_SO_NUMBER - 1]:
                continue
            so_number = str(row[COL_SO_NUMBER - 1]).strip()
            rec = _SORecord(so_number)
            rec.customer_name = row[COL_CUSTOMER_NAME - 1] or ""
            rec.customer_tag = row[COL_CUSTOMER_TAG - 1] or ""
            rec.order_date = _parse_date_value(row[COL_ORDER_DATE - 1])
            rec.po_date = _parse_date_value(row[COL_PO_DATE - 1])
            for i, component in enumerate(TRACKING_COLUMNS):
                rec.purchasing[component] = _normalize_choice(
                    row[_purchasing_col(i) - 1], PURCHASING_STATES, DEFAULT_PURCHASING_STATE
                )
                rec.production[component] = _normalize_tracking_status(row[_production_col(i) - 1])
            rec.shipping_status = _normalize_choice(
                row[COL_SHIPPING_STATUS - 1], SHIPPING_STATES, DEFAULT_SHIPPING_STATE
            )
            records[so_number] = rec

    def _parse_legacy_sheet(self, ws, header_row, records: Dict[str, _SORecord]):
        col_by_name = {str(v).strip(): i for i, v in enumerate(header_row) if v}
        # SO Number is always column A regardless of schema version — fall
        # back to position 0 if the header text itself got clobbered (an
        # earlier version of this sheet had a bug where the header write
        # could stomp a data row, leaving a stray value in A1).
        so_col_idx = col_by_name.get("SO Number", 0)

        def get(row, name):
            idx = col_by_name.get(name)
            return row[idx] if idx is not None and idx < len(row) else None

        shared_purchasing = None  # resolved per-row below

        for row in ws.iter_rows(min_row=DATA_START_ROW_LEGACY, values_only=True):
            if not row or so_col_idx >= len(row) or not row[so_col_idx]:
                continue
            so_number = str(row[so_col_idx]).strip()
            rec = _SORecord(so_number)
            rec.customer_name = get(row, "Customer Name") or ""
            rec.customer_tag = get(row, "Customer Tag / External Doc #") or ""
            rec.order_date = _parse_date_value(get(row, "Order Date"))
            rec.po_date = _parse_date_value(get(row, "PO Date"))
            shared_purchasing = _normalize_choice(
                get(row, LEGACY_SHARED_PURCHASING_STATUS), PURCHASING_STATES, DEFAULT_PURCHASING_STATE
            )
            for component in TRACKING_COLUMNS:
                rec.purchasing[component] = shared_purchasing
                rec.production[component] = _normalize_tracking_status(get(row, component))
            rec.shipping_status = _normalize_choice(
                get(row, "Shipping Status"), SHIPPING_STATES, DEFAULT_SHIPPING_STATE
            )
            records[so_number] = rec

    # ── build ───────────────────────────────────────────────────────────

    def _write_header(self, ws):
        """2-row grouped header. Fixed columns + Shipping Status span both
        rows (vertical merge); each component's name spans its Purchasing/
        Production pair (horizontal merge) with the sub-labels underneath.
        Written via direct cell assignment BEFORE any data rows are
        appended — ws.append() fills from row 1 on a fresh sheet, so writing
        header values after appending data would silently clobber the first
        data row (a real bug this file used to have)."""
        vertical = {
            COL_SO_NUMBER: "SO Number",
            COL_CUSTOMER_NAME: "Customer Name",
            COL_CUSTOMER_TAG: "Customer Tag / External Doc #",
            COL_ORDER_DATE: "Order Date",
            COL_PO_DATE: "PO Date",
            COL_SHIPPING_STATUS: "Shipping Status",
        }
        for col_idx, title in vertical.items():
            ws.cell(row=1, column=col_idx, value=title)
            ws.merge_cells(start_row=1, start_column=col_idx, end_row=2, end_column=col_idx)

        for i, component in enumerate(TRACKING_COLUMNS):
            p_col, d_col = _purchasing_col(i), _production_col(i)
            ws.cell(row=1, column=p_col, value=component)
            ws.merge_cells(start_row=1, start_column=p_col, end_row=1, end_column=d_col)
            ws.cell(row=2, column=p_col, value="Purchasing")
            ws.cell(row=2, column=d_col, value="Production")

    def _style_sheet(self, ws, archived: bool = False):
        ws.freeze_panes = "B3"
        max_row = max(ws.max_row, DATA_START_ROW_V3)
        last_col_letter = get_column_letter(TOTAL_COLUMNS)
        ws.auto_filter.ref = f"A2:{last_col_letter}{max_row}"

        for col_idx in range(1, TOTAL_COLUMNS + 1):
            for r in (1, 2):
                cell = ws.cell(row=r, column=col_idx)
                cell.fill = HEADER_FILL if r == 1 else SUBHEADER_FILL
                cell.font = HEADER_FONT
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        widths = [14, 28, 26, 13, 13]
        for _ in TRACKING_COLUMNS:
            widths += [15, 13]
        widths += [15]
        for col_idx, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        ws.row_dimensions[1].height = 22
        ws.row_dimensions[2].height = 22

        for col_idx in (COL_ORDER_DATE, COL_PO_DATE):
            for r in range(DATA_START_ROW_V3, max_row + 1):
                ws.cell(row=r, column=col_idx).number_format = DATE_FORMAT

        def add_dropdown(col_idx, choices, allow_blank_entry=False):
            col_letter = get_column_letter(col_idx)
            rng = f"{col_letter}{DATA_START_ROW_V3}:{col_letter}{max_row}"
            if not archived:
                options = list(choices) + [""] if allow_blank_entry else list(choices)
                dv = DataValidation(type="list", formula1=f'"{",".join(options)}"', allow_blank=True)
                ws.add_data_validation(dv)
                dv.add(rng)
            return rng

        for i, _component in enumerate(TRACKING_COLUMNS):
            # Purchasing: red -> amber -> blue -> purple -> green
            rng = add_dropdown(_purchasing_col(i), PURCHASING_STATES)
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Waiting to Order"'], fill=RED_FILL, font=RED_FONT))
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Ordered"'], fill=AMBER_FILL, font=AMBER_FONT))
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Shipped by Vendor"'], fill=BLUE_FILL, font=BLUE_FONT))
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"In Stock"'], fill=PURPLE_FILL, font=PURPLE_FONT))
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Received"'], fill=GREEN_FILL, font=GREEN_FONT))

            # Production: green / red / blank-white, with N/A dropdown entry
            rng = add_dropdown(_production_col(i), [COMPLETE, NOT_COMPLETE], allow_blank_entry=True)
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{NOT_COMPLETE}"'], fill=RED_FILL, font=RED_FONT))
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{COMPLETE}"'], fill=GREEN_FILL, font=GREEN_FONT))
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['""'], fill=WHITE_FILL, font=WHITE_FONT))

        # Shipping Status: red -> amber -> green
        rng = add_dropdown(COL_SHIPPING_STATUS, SHIPPING_STATES)
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Not Ready"'], fill=RED_FILL, font=RED_FONT))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Ready to Ship"'], fill=AMBER_FILL, font=AMBER_FONT))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Shipped"'], fill=GREEN_FILL, font=GREEN_FONT))

        for row in ws.iter_rows(min_row=DATA_START_ROW_V3, max_row=max_row):
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
        self._write_header(ws)  # must happen before any ws.append() — see docstring

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
        self._write_header(ws_archived)
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
