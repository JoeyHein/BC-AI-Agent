"""
Production schedule workbook — BOX IN, BOX OUT model (2026-10-02).

OPENDC is a distributor now: every sales order is bought COMPLETE from
Upwardor on a PO that mirrors the SO 1:1 (so_po_generation_service,
mode="complete"). The only in-house work by default is installing window
kits. Building doors in-house is the exception — an "Emergency Build" for a
customer who can't wait. So the Schedule sheet is one row per open SO:

  SO Number | Customer Name | Customer Tag / External Doc # | Order Date |
  PO Date | Fulfillment | Upwardor PO # | Order Status | Expected Receipt |
  Operators | Window Kits | Emergency Build | Shipping Status

- Fulfillment: "Buy Complete" (default) or "Emergency Build" — hand-set.
  BC still auto-creates production orders for most SOs (190 released prod
  orders linked to 40/54 open SOs on 2026-10-02), so a production order is
  NOT a reliable emergency signal; a person flips this.
- Upwardor PO # / Expected Receipt: read-only, refreshed every run from the
  BC purchase orders that reference the SO ("Built from SO-…" comment lines
  or externalDocumentNumber — draft_po_review_service._sales_orders_from_po).
- Order Status (Waiting to Order → PO Drafted → Ordered → Shipped by Vendor
  → Partially Received → Received): auto-derived from those PO lines, and
  only ever ADVANCES — a refresh never moves it backward, so a hand-set
  "Shipped by Vendor" (not derivable from BC) survives until BC shows the
  receipt.
- Operators: same states, from the OP* lines (operators are bought direct
  from the maker, never on the Upwardor PO). Blank when the SO has no
  operator.
- Window Kits: blank when the SO has no GK* items; seeded "Not Started"
  when it does, then hand-edited (In Progress / Complete).
- Emergency Build: blank unless Fulfillment is "Emergency Build"; seeded
  "Not Started" when flipped, then hand-edited (In Production / Complete).

Every rebuild reads back the current SharePoint file FIRST and carries edits
forward keyed by SO number, then overwrites the file in place. Read-back is
by HEADER NAME (not position) so adding a column later can't silently wipe
rows — see parse_records_from_bytes. It also migrates the two previous
layouts (v3: 7 components × Purchasing/Production; legacy: 1-row header).
SOs that drop out of BC's open set move to an "Archived" sheet.

"Assignments" sheet — Joey's curated, prioritized shop queue, keyed by SALES
ORDER. Paste an SO # onto a MAIN line; Customer auto-fills and the SO's
in-house work lists as read-only SUB-LINES beneath it (Excel outline
grouping): one line per window-kit item, plus — for Emergency Build SOs only
— each BC production order linked to it. Priority/Assigned To/Complete By
are typed once on the main line. Auto-closes once BC no longer reports the
SO open; an SO # that never matched stays flagged "NOT FOUND". A main line
also shows a read-only "Picking Remaining" summary from the Upwardor picking
extension (blank until deployed — see bc-extension/picking-api/README.md).

"Purchase Orders" sheet — read-only, one row per (open SO, BC purchase
order) from the same PO linkage, with receipt progress.
"""

import io
import logging
import re
from collections import defaultdict
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
from app.services.bc_production_service import bc_production_service, ODATA_ENDPOINTS

logger = logging.getLogger(__name__)

# ── states ──────────────────────────────────────────────────────────────
BUY_COMPLETE = "Buy Complete"
EMERGENCY_BUILD = "Emergency Build"
FULFILLMENT_STATES = [BUY_COMPLETE, EMERGENCY_BUILD]

WAITING_TO_ORDER = "Waiting to Order"
PO_DRAFTED = "PO Drafted"
ORDERED = "Ordered"
SHIPPED_BY_VENDOR = "Shipped by Vendor"
PARTIALLY_RECEIVED = "Partially Received"
RECEIVED = "Received"
ORDER_STATES = [WAITING_TO_ORDER, PO_DRAFTED, ORDERED, SHIPPED_BY_VENDOR, PARTIALLY_RECEIVED, RECEIVED]
_ORDER_RANK = {s: i for i, s in enumerate(ORDER_STATES)}

NOT_STARTED = "Not Started"
IN_PROGRESS = "In Progress"
IN_PRODUCTION = "In Production"
COMPLETE = "Complete"
WINDOW_KIT_STATES = [NOT_STARTED, IN_PROGRESS, COMPLETE]
BUILD_STATES = [NOT_STARTED, IN_PRODUCTION, COMPLETE]
NOT_APPLICABLE = ""  # blank — that kind of work isn't on this order

SHIPPING_STATES = ["Not Ready", "Ready to Ship", "Shipped"]
DEFAULT_SHIPPING_STATE = "Not Ready"

# Window kits are the one thing still done in-house on a buy-complete order.
WINDOW_KIT_PREFIXES = ("GK",)
# Operators never ride on the Upwardor PO — bought direct from the maker.
OPERATOR_PREFIXES = ("OP",)

# ── Schedule column layout (1-indexed) ──────────────────────────────────
SCHEDULE_HEADERS = [
    "SO Number", "Customer Name", "Customer Tag / External Doc #", "Order Date", "PO Date",
    "Fulfillment", "Upwardor PO #", "Order Status", "Expected Receipt",
    "Operators", "Window Kits", "Emergency Build", "Shipping Status",
]
COL = {name: i for i, name in enumerate(SCHEDULE_HEADERS, start=1)}
TOTAL_COLUMNS = len(SCHEDULE_HEADERS)
DATA_START_ROW = 2
AUTO_COLUMNS = ("Upwardor PO #", "Expected Receipt")  # read-only, refreshed every run

# ── previous layouts, kept only to migrate live files ──────────────────
_V3_COMPONENTS = ["Panels", "Hardware", "Tracks", "Springs", "Shafts", "Weather Stripping", "Operators"]
_V3_FIRST_COMPONENT_COL = 6
_V3_SHIPPING_COL = _V3_FIRST_COMPONENT_COL + len(_V3_COMPONENTS) * 2  # 20
_V3_DATA_START_ROW = 3
_LEGACY_DATA_START_ROW = 2

# ── Assignments sheet (Joey's curated, prioritized shop queue) ──────────
ASSIGN_SHEET_NAME = "Assignments"
COL_A_PRIORITY = 1
COL_A_SO_NUMBER = 2
COL_A_CUSTOMER = 3
COL_A_ASSIGNED_TO = 4
COL_A_COMPLETE_BY = 5
COL_A_PICKING_REMAINING = 6
COL_A_WORK = 7
COL_A_ITEM = 8
COL_A_DESCRIPTION = 9
COL_A_QTY = 10
COL_A_STATUS = 11
COL_A_DUE_DATE = 12
ASSIGN_HEADERS = ["Priority", "SO Number", "Customer", "Assigned To", "Complete By",
                   "Picking Remaining", "Work", "Item", "Description", "Qty",
                   "Status", "Due Date"]
ASSIGN_TOTAL_COLUMNS = COL_A_DUE_DATE

PO_LINKS_SHEET_NAME = "Purchase Orders"
PO_LINKS_HEADERS = ["SO Number", "Customer", "PO Number", "Vendor", "PO Status",
                     "Lines", "Received", "Expected Receipt"]

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
ORANGE_FILL = PatternFill(start_color="F8CBAD", end_color="F8CBAD", fill_type="solid")
ORANGE_FONT = Font(color="833C0B", bold=True)
AUTO_FILL = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
AUTO_HEADER_FILL = PatternFill(start_color="595959", end_color="595959", fill_type="solid")
ARCHIVED_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")

DATE_FORMAT = "mm/dd/yyyy"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sort_key(so_number: str):
    digits = re.sub(r"\D", "", so_number or "")
    return int(digits) if digits else 0


def _normalize_choice(value, choices: List[str], default: str) -> str:
    value = (str(value).strip() if value else "")
    return value if value in choices else default


def _parse_date_value(value) -> Optional[date]:
    """Accept a datetime/date (openpyxl's native read for date-formatted
    cells) or an ISO-ish string (BC's orderDate, or hand-typed text). BC's
    0001-01-01 null-date sentinel reads as None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        parsed = datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None
    return None if parsed.year <= 1 else parsed


def _has_prefix(item_no: str, prefixes: Tuple[str, ...]) -> bool:
    return (item_no or "").upper().startswith(prefixes)


def _advance(current: str, computed: Optional[str]) -> str:
    """Order Status / Operators only ever move FORWARD on refresh — a hand-set
    later state (e.g. Shipped by Vendor, which BC can't tell us) is never
    pulled back by an auto value that hasn't caught up yet."""
    if not computed:
        return current
    if not current or _ORDER_RANK.get(computed, -1) > _ORDER_RANK.get(current, -1):
        return computed
    return current


def _order_status_from_lines(lines: List[dict]) -> Optional[str]:
    """Status of one group of BC purchase-order item lines (each carrying its
    PO's `_po_status`). None when there are no lines."""
    if not lines:
        return None
    qty = sum(float(l.get("quantity") or 0) for l in lines)
    received = sum(min(float(l.get("receivedQuantity") or 0), float(l.get("quantity") or 0)) for l in lines)
    if qty > 0 and received >= qty:
        return RECEIVED
    if received > 0:
        return PARTIALLY_RECEIVED
    if any((l.get("_po_status") or "") != "Draft" for l in lines):
        return ORDERED
    return PO_DRAFTED


class _SORecord:
    """One sales order's full row state — fresh BC fields plus whatever's
    hand-edited. Used both for currently-open rows and for the Archived
    sheet snapshot of orders no longer open."""

    __slots__ = (
        "so_number", "customer_name", "customer_tag", "order_date", "po_date",
        "fulfillment", "po_numbers", "order_status", "expected_receipt",
        "operators", "window_kits", "emergency_build", "shipping_status",
    )

    def __init__(self, so_number: str):
        self.so_number = so_number
        self.customer_name = ""
        self.customer_tag = ""
        self.order_date: Optional[date] = None
        self.po_date: Optional[date] = None
        self.fulfillment = BUY_COMPLETE
        self.po_numbers = ""
        self.order_status = WAITING_TO_ORDER
        self.expected_receipt: Optional[date] = None
        self.operators = NOT_APPLICABLE
        self.window_kits = NOT_APPLICABLE
        self.emergency_build = NOT_APPLICABLE
        self.shipping_status = DEFAULT_SHIPPING_STATE

    def to_row(self) -> list:
        return [
            self.so_number, self.customer_name, self.customer_tag, self.order_date, self.po_date,
            self.fulfillment, self.po_numbers, self.order_status, self.expected_receipt,
            self.operators, self.window_kits, self.emergency_build, self.shipping_status,
        ]


class ProductionScheduleService:

    # ── BC data ─────────────────────────────────────────────────────────

    def fetch_open_orders(self) -> List[Dict[str, Any]]:
        """All in-flight sales orders from BC, WITH their lines expanded.

        BC's salesOrders v2.0 entity only ever holds non-posted orders, so no
        status filter is needed to exclude completed work. "Draft" there just
        means not yet released — still a real order. Only an explicit
        Cancelled status is excluded."""
        orders = bc_client.get_open_sales_orders_with_lines()
        orders = [o for o in orders if "cancel" not in (o.get("status") or "").lower()]
        orders.sort(key=lambda o: _sort_key(o.get("number", "")))
        return orders

    def fetch_po_lines_by_so(self) -> Dict[str, List[dict]]:
        """{so_number: [PO item line + _po_number/_po_status/_vendor]} for every
        non-posted BC purchase order that references the SO. Best-effort —
        BC failure degrades to {} (statuses then just don't advance)."""
        from app.services.draft_po_review_service import _sales_orders_from_po
        try:
            pos = bc_client.get_open_purchase_orders_with_lines()
        except Exception as e:
            logger.error(f"[ProductionSchedule] Purchase orders fetch failed: {e}")
            return {}
        by_so: Dict[str, List[dict]] = defaultdict(list)
        for po in pos:
            lines = po.get("purchaseOrderLines") or []
            for so in _sales_orders_from_po(po, lines):
                for ln in lines:
                    if ln.get("lineType") != "Item" or not ln.get("lineObjectNumber"):
                        continue
                    by_so[so].append({
                        **ln,
                        "_po_number": po.get("number") or "",
                        "_po_status": po.get("status") or "",
                        "_vendor": po.get("vendorName") or "",
                    })
        return dict(by_so)

    def compute_so_facts(
        self, orders: List[Dict[str, Any]], po_lines_by_so: Dict[str, List[dict]],
    ) -> Dict[str, dict]:
        """Per-SO auto-derived facts for the Schedule + Assignments sheets:
        {so_number: {po_numbers, order_status, expected_receipt, operators,
        window_kit_lines}}. order_status/operators are None when there's
        nothing on the SO to buy in that group."""
        from app.services.purchasing_demand_service import NON_STOCK_ITEMS
        from app.services.so_po_generation_service import _complete_mode_exclusion

        facts: Dict[str, dict] = {}
        for order in orders:
            so = order.get("number", "")
            needs_main = needs_operator = False
            window_kit_lines = []
            for ln in order.get("salesOrderLines", []):
                item = ln.get("lineObjectNumber") or ""
                if ln.get("lineType") != "Item" or not item or item.upper() in NON_STOCK_ITEMS:
                    continue
                if _has_prefix(item, OPERATOR_PREFIXES):
                    needs_operator = True
                elif not _complete_mode_exclusion(item):
                    needs_main = True
                if _has_prefix(item, WINDOW_KIT_PREFIXES):
                    window_kit_lines.append({
                        "item": item,
                        "description": ln.get("description") or "",
                        "qty": float(ln.get("quantity") or 0),
                    })

            po_lines = po_lines_by_so.get(so, [])
            main_lines = [l for l in po_lines if not _has_prefix(l.get("lineObjectNumber"), OPERATOR_PREFIXES)]
            op_lines = [l for l in po_lines if _has_prefix(l.get("lineObjectNumber"), OPERATOR_PREFIXES)]

            order_status = _order_status_from_lines(main_lines) or (WAITING_TO_ORDER if needs_main else None)
            operators = _order_status_from_lines(op_lines) or (WAITING_TO_ORDER if needs_operator else None)

            outstanding_dates = [
                d for d in (
                    _parse_date_value(l.get("expectedReceiptDate")) for l in main_lines
                    if float(l.get("receivedQuantity") or 0) < float(l.get("quantity") or 0)
                ) if d
            ]
            facts[so] = {
                "po_numbers": ", ".join(sorted({l["_po_number"] for l in main_lines if l["_po_number"]})),
                "order_status": order_status,
                # Latest outstanding line — the order isn't complete until it lands.
                "expected_receipt": max(outstanding_dates) if outstanding_dates else None,
                "operators": operators,
                "window_kit_lines": window_kit_lines,
            }
        return facts

    # ── read-back ───────────────────────────────────────────────────────

    def parse_records_from_bytes(self, content: bytes) -> Dict[str, _SORecord]:
        """Return {so_number: _SORecord} read from an existing workbook's
        Schedule + Archived sheets. Detects the header generation:

        - v4 (this version, row 1 has "Fulfillment"): read by HEADER NAME, so
          a sheet written before/after a column was added still parses.
        - v3 (2 header rows, 7 components × Purchasing/Production): migrated.
          Per-component production status is dropped (not tracked anymore);
          only a hand-set "Shipped by Vendor" carries into Order Status — the
          old Received/In Stock values meant raw components on hand for an
          in-house build, not the finished order. Operators carries as-is.
        - legacy (1-row header): PO Date / Shipping Status carry by name.
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
            if any(str(v).strip() == "Fulfillment" for v in row1 if v):
                self._parse_v4_sheet(ws, row1, records)
            elif any(str(v).strip() in ("Purchasing", "Production") for v in row2 if v):
                self._parse_v3_sheet(ws, records)
            else:
                self._parse_legacy_sheet(ws, row1, records)
        return records

    def _parse_v4_sheet(self, ws, header_row, records: Dict[str, _SORecord]):
        col_by_name = {str(v).strip(): i for i, v in enumerate(header_row) if v}
        so_idx = col_by_name.get("SO Number", 0)

        def get(row, name):
            idx = col_by_name.get(name)
            return row[idx] if idx is not None and idx < len(row) else None

        for row in ws.iter_rows(min_row=DATA_START_ROW, values_only=True):
            if not row or so_idx >= len(row) or not row[so_idx]:
                continue
            rec = _SORecord(str(row[so_idx]).strip())
            rec.customer_name = get(row, "Customer Name") or ""
            rec.customer_tag = get(row, "Customer Tag / External Doc #") or ""
            rec.order_date = _parse_date_value(get(row, "Order Date"))
            rec.po_date = _parse_date_value(get(row, "PO Date"))
            rec.fulfillment = _normalize_choice(get(row, "Fulfillment"), FULFILLMENT_STATES, BUY_COMPLETE)
            rec.po_numbers = get(row, "Upwardor PO #") or ""
            rec.order_status = _normalize_choice(get(row, "Order Status"), ORDER_STATES, WAITING_TO_ORDER)
            rec.expected_receipt = _parse_date_value(get(row, "Expected Receipt"))
            rec.operators = _normalize_choice(get(row, "Operators"), ORDER_STATES, NOT_APPLICABLE)
            rec.window_kits = _normalize_choice(get(row, "Window Kits"), WINDOW_KIT_STATES, NOT_APPLICABLE)
            rec.emergency_build = _normalize_choice(get(row, "Emergency Build"), BUILD_STATES, NOT_APPLICABLE)
            rec.shipping_status = _normalize_choice(get(row, "Shipping Status"), SHIPPING_STATES, DEFAULT_SHIPPING_STATE)
            records[rec.so_number] = rec

    def _parse_v3_sheet(self, ws, records: Dict[str, _SORecord]):
        for row in ws.iter_rows(min_row=_V3_DATA_START_ROW, values_only=True):
            if not row or not row[0]:
                continue
            row = tuple(row) + (None,) * max(0, _V3_SHIPPING_COL - len(row))
            rec = _SORecord(str(row[0]).strip())
            rec.customer_name = row[1] or ""
            rec.customer_tag = row[2] or ""
            rec.order_date = _parse_date_value(row[3])
            rec.po_date = _parse_date_value(row[4])
            purchasing = {
                c: str(row[_V3_FIRST_COMPONENT_COL - 1 + i * 2] or "").strip()
                for i, c in enumerate(_V3_COMPONENTS)
            }
            if any(v == SHIPPED_BY_VENDOR for c, v in purchasing.items() if c != "Operators"):
                rec.order_status = SHIPPED_BY_VENDOR
            op = "Received" if purchasing["Operators"] == "In Stock" else purchasing["Operators"]
            # Old default "Waiting to Order" was written for every SO, operator
            # or not — let the fresh SO lines decide whether it applies.
            rec.operators = op if op in ORDER_STATES and op != WAITING_TO_ORDER else NOT_APPLICABLE
            rec.shipping_status = _normalize_choice(row[_V3_SHIPPING_COL - 1], SHIPPING_STATES, DEFAULT_SHIPPING_STATE)
            records[rec.so_number] = rec

    def _parse_legacy_sheet(self, ws, header_row, records: Dict[str, _SORecord]):
        col_by_name = {str(v).strip(): i for i, v in enumerate(header_row) if v}
        so_idx = col_by_name.get("SO Number", 0)

        def get(row, name):
            idx = col_by_name.get(name)
            return row[idx] if idx is not None and idx < len(row) else None

        for row in ws.iter_rows(min_row=_LEGACY_DATA_START_ROW, values_only=True):
            if not row or so_idx >= len(row) or not row[so_idx]:
                continue
            rec = _SORecord(str(row[so_idx]).strip())
            rec.customer_name = get(row, "Customer Name") or ""
            rec.customer_tag = get(row, "Customer Tag / External Doc #") or ""
            rec.order_date = _parse_date_value(get(row, "Order Date"))
            rec.po_date = _parse_date_value(get(row, "PO Date"))
            rec.shipping_status = _normalize_choice(get(row, "Shipping Status"), SHIPPING_STATES, DEFAULT_SHIPPING_STATE)
            records[rec.so_number] = rec

    # ── Assignments sheet: fetch + read-back ──────────────────────────────

    def fetch_open_production_orders(self) -> List[Dict[str, Any]]:
        """Released BC production orders — only surfaced under Emergency
        Build SOs now. Best-effort: BC failure degrades to []."""
        try:
            return bc_production_service._make_odata_request_all(
                ODATA_ENDPOINTS["production_orders"],
                query_params={"$filter": "Status eq 'Released'"},
            ) or []
        except Exception as e:
            logger.error(f"[ProductionSchedule] Released production orders fetch failed: {e}")
            return []

    def fetch_prod_so_map(self) -> Dict[str, str]:
        """{prod_order_no: sales_order_no}, best-effort — see
        bc_production_service.get_prod_so_map."""
        try:
            return bc_production_service.get_prod_so_map()
        except Exception as e:
            logger.warning(f"[ProductionSchedule] Prod-order/SO map unavailable: {e}")
            return {}

    def fetch_picking_remaining(self, so_numbers: Optional[List[str]] = None) -> Dict[str, dict]:
        """Live remaining-to-pick summary per SO, best-effort — see
        picking_activity_service.get_remaining_to_pick. Degrades to {} until
        the Upwardor picking extension is deployed (page 70141)."""
        try:
            from app.services.picking_activity_service import picking_activity_service
            return picking_activity_service.get_remaining_to_pick(so_numbers=so_numbers)
        except Exception as e:
            logger.warning(f"[ProductionSchedule] Picking-remaining unavailable: {e}")
            return {}

    def parse_assignments_from_bytes(self, content: bytes) -> Dict[str, dict]:
        """Return {so_number: {priority, assigned_to, complete_by, customer}}
        read from the Assignments sheet's MAIN (SO) lines only — a row with a
        value in the SO Number column. Sub-lines carry no persisted state."""
        records: Dict[str, dict] = {}
        if not content:
            return records
        try:
            wb = load_workbook(io.BytesIO(content))
        except Exception as e:
            logger.warning(f"[ProductionSchedule] Assignments read-back: could not open workbook ({e})")
            return records
        if ASSIGN_SHEET_NAME not in wb.sheetnames:
            return records

        ws = wb[ASSIGN_SHEET_NAME]
        for row in ws.iter_rows(min_row=2, values_only=True):
            # Only columns up to COL_A_COMPLETE_BY are read here — checking
            # against ASSIGN_TOTAL_COLUMNS instead would reject every row
            # whenever a sheet still on an older (narrower) schema gets
            # read back, silently wiping all hand-typed data. Bit us once
            # (2026-08-25) when the Picking Remaining column widened the
            # sheet from 11 to 12 columns.
            if not row or len(row) < COL_A_COMPLETE_BY or not row[COL_A_SO_NUMBER - 1]:
                continue  # blank SO Number == a sub-line, not a main line
            so_no = str(row[COL_A_SO_NUMBER - 1]).strip()
            priority_raw = row[COL_A_PRIORITY - 1]
            assigned_to = row[COL_A_ASSIGNED_TO - 1]
            try:
                priority = int(priority_raw) if priority_raw not in (None, "") else None
            except (TypeError, ValueError):
                priority = None
            records[so_no] = {
                "priority": priority,
                "assigned_to": str(assigned_to).strip() if assigned_to else "",
                "complete_by": _parse_date_value(row[COL_A_COMPLETE_BY - 1]),
                "customer": row[COL_A_CUSTOMER - 1] or "",
            }
        return records

    def _write_assignments_sheet(
        self,
        wb: Workbook,
        prod_orders: List[Dict[str, Any]],
        prior: Dict[str, dict],
        prod_so_map: Optional[Dict[str, str]] = None,
        so_customer_map: Optional[Dict[str, str]] = None,
        picking_remaining: Optional[Dict[str, dict]] = None,
        so_work: Optional[Dict[str, dict]] = None,
    ) -> None:
        """Add/replace the Assignments sheet: ONLY the sales orders in
        `prior` (jobs Joey has put here), sorted by Priority. Each SO is a
        MAIN line; its in-house work lists as read-only SUB-LINES beneath it:

        - one "Window Kit" line per GK item on the SO (status = the SO's
          Window Kits status from the Schedule sheet);
        - for Emergency Build SOs only, every BC production order linked to
          it via `prod_so_map`. Buy-complete SOs' production orders are BC
          noise (it still auto-creates them) and are not shown.

        `so_work` is {so_number: {"fulfillment", "window_kits",
        "window_kit_lines"}}.

        Auto-close: a main line that previously had a confirmed customer
        match but whose SO is no longer open in BC is dropped. An SO # that
        never matched is kept and flagged "NOT FOUND"."""
        prod_so_map = prod_so_map or {}
        so_customer_map = so_customer_map or {}
        picking_remaining = picking_remaining or {}
        so_work = so_work or {}
        fresh_by_po = {po.get("No"): po for po in prod_orders if po.get("No")}
        so_to_pos: Dict[str, List[str]] = defaultdict(list)
        for po_no, so_no in prod_so_map.items():
            so_to_pos[so_no].append(po_no)

        if ASSIGN_SHEET_NAME in wb.sheetnames:
            del wb[ASSIGN_SHEET_NAME]
        ws = wb.create_sheet(ASSIGN_SHEET_NAME)

        for c, title in enumerate(ASSIGN_HEADERS, start=1):
            cell = ws.cell(row=1, column=c, value=title)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
        ws.freeze_panes = "A2"
        # Summary (main) row sits ABOVE its detail (sub-line) rows, so
        # collapsing a group hides the rows below the SO line — not above it.
        ws.sheet_properties.outlinePr.summaryBelow = False

        groups = []
        for so_no, rec in prior.items():
            fresh_customer = so_customer_map.get(so_no)
            had_confirmed_match = bool(rec.get("customer"))
            if fresh_customer is None and had_confirmed_match:
                continue  # SO no longer open — finished/invoiced, auto-close
            not_found = fresh_customer is None
            customer = fresh_customer if not not_found else "NOT FOUND"
            work = so_work.get(so_no, {})
            emergency = work.get("fulfillment") == EMERGENCY_BUILD

            sub_rows = [{
                "work": "Window Kit",
                "item": wk["item"],
                "description": wk["description"],
                "qty": wk["qty"],
                "status": work.get("window_kits") or NOT_STARTED,
                "due_date": None,
            } for wk in work.get("window_kit_lines", [])]

            if emergency:
                build_rows = []
                for po_no in so_to_pos.get(so_no, []):
                    po = fresh_by_po.get(po_no)
                    if not po:
                        continue  # that production order finished — drops quietly
                    build_rows.append({
                        "work": po_no,
                        "item": po.get("Source_No") or "",
                        "description": po.get("Description") or "",
                        "qty": float(po.get("Quantity") or 0),
                        "status": po.get("Status") or "",
                        "due_date": _parse_date_value(po.get("Due_Date")),
                    })
                build_rows.sort(key=lambda r: (r["due_date"] is None, r["due_date"] or date.max, r["work"]))
                sub_rows += build_rows

            pick = picking_remaining.get(so_no)
            picking_display = f"{pick['lines_remaining']} items / {pick['qty_remaining']:g} units" if pick else ""

            groups.append({
                "so_no": so_no,
                "priority": rec.get("priority"),
                "customer": customer,
                "not_found": not_found,
                "emergency": emergency,
                "assigned_to": rec.get("assigned_to", ""),
                "complete_by": rec.get("complete_by"),
                "picking_display": picking_display,
                "sub_rows": sub_rows,
            })

        # Priority order — blank priority sinks to the bottom rather than
        # disappearing, so an unprioritized addition is still visible.
        groups.sort(key=lambda g: (g["priority"] is None, g["priority"] if g["priority"] is not None else 0, g["so_no"]))

        main_font = Font(bold=True)

        row_i = 2
        for g in groups:
            ws.cell(row=row_i, column=COL_A_PRIORITY, value=g["priority"])
            ws.cell(row=row_i, column=COL_A_SO_NUMBER, value=g["so_no"])
            ws.cell(row=row_i, column=COL_A_CUSTOMER, value=g["customer"])
            assigned_cell = ws.cell(row=row_i, column=COL_A_ASSIGNED_TO, value=g["assigned_to"])
            cb = ws.cell(row=row_i, column=COL_A_COMPLETE_BY, value=g["complete_by"])
            cb.number_format = DATE_FORMAT
            ws.cell(row=row_i, column=COL_A_PICKING_REMAINING, value=g["picking_display"])
            if g["emergency"]:
                ws.cell(row=row_i, column=COL_A_WORK, value=EMERGENCY_BUILD)
            for col in range(1, len(ASSIGN_HEADERS) + 1):
                ws.cell(row=row_i, column=col).font = main_font
            if g["not_found"]:
                for col in range(1, len(ASSIGN_HEADERS) + 1):
                    ws.cell(row=row_i, column=col).fill = ARCHIVED_FILL
            else:
                if g["emergency"]:
                    work_cell = ws.cell(row=row_i, column=COL_A_WORK)
                    work_cell.fill = ORANGE_FILL
                    work_cell.font = ORANGE_FONT
                if not g["assigned_to"]:
                    assigned_cell.fill = AMBER_FILL
            row_i += 1

            for sub in g["sub_rows"]:
                ws.cell(row=row_i, column=COL_A_WORK, value=sub["work"])
                ws.cell(row=row_i, column=COL_A_ITEM, value=sub["item"])
                ws.cell(row=row_i, column=COL_A_DESCRIPTION, value=sub["description"])
                ws.cell(row=row_i, column=COL_A_QTY, value=sub["qty"])
                ws.cell(row=row_i, column=COL_A_STATUS, value=sub["status"])
                dd = ws.cell(row=row_i, column=COL_A_DUE_DATE, value=sub["due_date"])
                dd.number_format = DATE_FORMAT
                ws.row_dimensions[row_i].outlineLevel = 1
                row_i += 1

        widths = [9, 14, 22, 18, 13, 20, 16, 18, 30, 8, 14, 13]
        for col_idx, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = w

    def _write_po_links_sheet(
        self,
        wb: Workbook,
        po_lines_by_so: Optional[Dict[str, List[dict]]],
        so_customer_map: Optional[Dict[str, str]] = None,
    ) -> None:
        """Add/replace the read-only "Purchase Orders" sheet — one row per
        (open SO, BC purchase order) that references it, with receipt
        progress. Rebuilt from scratch every refresh; nothing hand-edited."""
        po_lines_by_so = po_lines_by_so or {}
        so_customer_map = so_customer_map or {}
        if PO_LINKS_SHEET_NAME in wb.sheetnames:
            del wb[PO_LINKS_SHEET_NAME]
        ws = wb.create_sheet(PO_LINKS_SHEET_NAME)

        for c, title in enumerate(PO_LINKS_HEADERS, start=1):
            cell = ws.cell(row=1, column=c, value=title)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
        ws.freeze_panes = "A2"

        rows = []
        for so_no, lines in po_lines_by_so.items():
            if so_no not in so_customer_map:
                continue  # only open SOs
            by_po: Dict[str, List[dict]] = defaultdict(list)
            for ln in lines:
                by_po[ln["_po_number"]].append(ln)
            for po_no, po_lines in by_po.items():
                outstanding = [
                    _parse_date_value(l.get("expectedReceiptDate")) for l in po_lines
                    if float(l.get("receivedQuantity") or 0) < float(l.get("quantity") or 0)
                ]
                outstanding = [d for d in outstanding if d]
                received = sum(1 for l in po_lines
                               if float(l.get("quantity") or 0) > 0
                               and float(l.get("receivedQuantity") or 0) >= float(l.get("quantity") or 0))
                rows.append({
                    "so_number": so_no,
                    "customer": so_customer_map.get(so_no, ""),
                    "po_number": po_no,
                    "vendor": po_lines[0]["_vendor"],
                    "status": po_lines[0]["_po_status"],
                    "lines": len(po_lines),
                    "received": f"{received}/{len(po_lines)}",
                    "expected": max(outstanding) if outstanding else None,
                })
        rows.sort(key=lambda r: (_sort_key(r["so_number"]), r["po_number"]))

        for i, r in enumerate(rows, start=2):
            ws.cell(row=i, column=1, value=r["so_number"])
            ws.cell(row=i, column=2, value=r["customer"])
            ws.cell(row=i, column=3, value=r["po_number"])
            ws.cell(row=i, column=4, value=r["vendor"])
            ws.cell(row=i, column=5, value=r["status"])
            ws.cell(row=i, column=6, value=r["lines"])
            ws.cell(row=i, column=7, value=r["received"])
            ex = ws.cell(row=i, column=8, value=r["expected"])
            ex.number_format = DATE_FORMAT

        widths = [14, 24, 14, 22, 10, 8, 10, 16]
        for col_idx, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = w

    # ── build ───────────────────────────────────────────────────────────

    def _style_sheet(self, ws, archived: bool = False):
        ws.freeze_panes = "B2"
        max_row = max(ws.max_row, DATA_START_ROW)
        ws.auto_filter.ref = f"A1:{get_column_letter(TOTAL_COLUMNS)}{max_row}"

        for name, col_idx in COL.items():
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = AUTO_HEADER_FILL if name in AUTO_COLUMNS else HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 32

        widths = [14, 28, 26, 12, 12, 16, 16, 18, 13, 18, 14, 16, 15]
        for col_idx, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        for name in ("Order Date", "PO Date", "Expected Receipt"):
            for r in range(DATA_START_ROW, max_row + 1):
                ws.cell(row=r, column=COL[name]).number_format = DATE_FORMAT

        def add_dropdown(name, choices, allow_blank_entry=False):
            col_letter = get_column_letter(COL[name])
            rng = f"{col_letter}{DATA_START_ROW}:{col_letter}{max_row}"
            if not archived:
                options = list(choices) + [""] if allow_blank_entry else list(choices)
                dv = DataValidation(type="list", formula1=f'"{",".join(options)}"', allow_blank=True)
                ws.add_data_validation(dv)
                dv.add(rng)
            return rng

        def color(rng, value, fill, font):
            ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{value}"'], fill=fill, font=font))

        # The anomaly should jump off the page.
        rng = add_dropdown("Fulfillment", FULFILLMENT_STATES)
        color(rng, EMERGENCY_BUILD, ORANGE_FILL, ORANGE_FONT)

        order_colors = [
            (WAITING_TO_ORDER, RED_FILL, RED_FONT),
            (PO_DRAFTED, AMBER_FILL, AMBER_FONT),
            (ORDERED, AMBER_FILL, AMBER_FONT),
            (SHIPPED_BY_VENDOR, BLUE_FILL, BLUE_FONT),
            (PARTIALLY_RECEIVED, PURPLE_FILL, PURPLE_FONT),
            (RECEIVED, GREEN_FILL, GREEN_FONT),
        ]
        for name in ("Order Status", "Operators"):
            rng = add_dropdown(name, ORDER_STATES, allow_blank_entry=True)
            for value, fill, font in order_colors:
                color(rng, value, fill, font)

        for name, states, middle in (("Window Kits", WINDOW_KIT_STATES, IN_PROGRESS),
                                     ("Emergency Build", BUILD_STATES, IN_PRODUCTION)):
            rng = add_dropdown(name, states, allow_blank_entry=True)
            color(rng, NOT_STARTED, RED_FILL, RED_FONT)
            color(rng, middle, AMBER_FILL, AMBER_FONT)
            color(rng, COMPLETE, GREEN_FILL, GREEN_FONT)

        rng = add_dropdown("Shipping Status", SHIPPING_STATES)
        color(rng, "Not Ready", RED_FILL, RED_FONT)
        color(rng, "Ready to Ship", AMBER_FILL, AMBER_FONT)
        color(rng, "Shipped", GREEN_FILL, GREEN_FONT)

        for row in ws.iter_rows(min_row=DATA_START_ROW, max_row=max_row):
            for cell in row:
                cell.alignment = Alignment(horizontal="center") if cell.column >= COL["Order Date"] else Alignment(horizontal="left")
                if archived:
                    cell.fill = ARCHIVED_FILL
                elif cell.column in (COL[n] for n in AUTO_COLUMNS):
                    cell.fill = AUTO_FILL

    def _write_schedule_sheet(self, ws, rows: List[list], archived: bool = False):
        for c, title in enumerate(SCHEDULE_HEADERS, start=1):
            ws.cell(row=1, column=c, value=title)
        for r_i, row in enumerate(rows, start=DATA_START_ROW):
            for c_i, value in enumerate(row, start=1):
                ws.cell(row=r_i, column=c_i, value=value)
        self._style_sheet(ws, archived=archived)

    def build_workbook_bytes(
        self,
        orders: List[Dict[str, Any]],
        records: Dict[str, _SORecord],
        so_facts: Optional[Dict[str, dict]] = None,
        prod_orders: Optional[List[Dict[str, Any]]] = None,
        assignment_records: Optional[Dict[str, dict]] = None,
        prod_so_map: Optional[Dict[str, str]] = None,
        picking_remaining: Optional[Dict[str, dict]] = None,
        po_lines_by_so: Optional[Dict[str, List[dict]]] = None,
    ) -> Tuple[bytes, int, int]:
        open_so_numbers = {o.get("number", "") for o in orders}
        so_facts = so_facts or {}

        wb = Workbook()
        ws = wb.active
        ws.title = "Schedule"

        rows = []
        so_work: Dict[str, dict] = {}
        for order in orders:
            so_number = order.get("number", "")
            rec = records.get(so_number) or _SORecord(so_number)
            facts = so_facts.get(so_number)
            # Fresh-from-BC fields always win; hand-edited fields carry forward.
            rec.customer_name = order.get("customerName", "")
            rec.customer_tag = order.get("externalDocumentNumber", "")
            rec.order_date = _parse_date_value(order.get("orderDate")) or rec.order_date
            if facts is not None:
                rec.po_numbers = facts["po_numbers"]
                rec.expected_receipt = facts["expected_receipt"]
                # Nothing on the SO for Upwardor (e.g. operator-only) -> blank.
                rec.order_status = (_advance(rec.order_status, facts["order_status"])
                                    if facts["order_status"] else NOT_APPLICABLE)
                rec.operators = (_advance(rec.operators, facts["operators"])
                                 if facts["operators"] else NOT_APPLICABLE)
                if not facts["window_kit_lines"]:
                    rec.window_kits = NOT_APPLICABLE
                elif not rec.window_kits:
                    rec.window_kits = NOT_STARTED
            if rec.fulfillment != EMERGENCY_BUILD:
                rec.emergency_build = NOT_APPLICABLE
            elif not rec.emergency_build:
                rec.emergency_build = NOT_STARTED
            rows.append(rec.to_row())
            so_work[so_number] = {
                "fulfillment": rec.fulfillment,
                "window_kits": rec.window_kits,
                "window_kit_lines": (facts or {}).get("window_kit_lines", []),
            }
        self._write_schedule_sheet(ws, rows)

        archived_so = sorted((so for so in records if so not in open_so_numbers), key=_sort_key)
        ws_archived = wb.create_sheet("Archived")
        self._write_schedule_sheet(ws_archived, [records[so].to_row() for so in archived_so], archived=True)

        so_customer_map = {o.get("number"): o.get("customerName", "") for o in orders if o.get("number")}
        self._write_assignments_sheet(
            wb, prod_orders or [], assignment_records or {}, prod_so_map, so_customer_map,
            picking_remaining, so_work,
        )
        self._write_po_links_sheet(wb, po_lines_by_so, so_customer_map)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), len(orders), len(archived_so)

    # ── orchestration ───────────────────────────────────────────────────

    def _refresh(self, existing: Optional[bytes]) -> Tuple[bytes, dict]:
        records: Dict[str, _SORecord] = {}
        assignment_records: Dict[str, dict] = {}
        if existing:
            records = self.parse_records_from_bytes(existing)
            assignment_records = self.parse_assignments_from_bytes(existing)

        orders = self.fetch_open_orders()
        po_lines_by_so = self.fetch_po_lines_by_so()
        so_facts = self.compute_so_facts(orders, po_lines_by_so)
        emergency_open = any(
            (records.get(o.get("number")) or _SORecord("")).fulfillment == EMERGENCY_BUILD for o in orders
        )
        # Production orders only matter under Emergency Build SOs now.
        prod_orders = self.fetch_open_production_orders() if emergency_open else []
        prod_so_map = self.fetch_prod_so_map() if emergency_open else {}
        picking_remaining = self.fetch_picking_remaining(so_numbers=list(assignment_records.keys()))
        xlsx, open_count, archived_count = self.build_workbook_bytes(
            orders, records, so_facts,
            prod_orders=prod_orders, assignment_records=assignment_records, prod_so_map=prod_so_map,
            picking_remaining=picking_remaining, po_lines_by_so=po_lines_by_so,
        )
        return xlsx, {
            "open_orders": open_count,
            "archived_orders": archived_count,
            "emergency_builds": sum(
                1 for o in orders
                if (records.get(o.get("number")) or _SORecord("")).fulfillment == EMERGENCY_BUILD
            ),
            "assigned": len(assignment_records),
        }

    def build_and_deliver(self) -> dict:
        """Download current SharePoint copy (if any), merge in fresh BC
        orders preserving hand-edited status, and overwrite the file in
        place. Requires PRODSCHED_SHAREPOINT_ENABLED + DRIVE_ID configured."""
        if not (settings.PRODSCHED_SHAREPOINT_ENABLED and settings.PRODSCHED_SHAREPOINT_DRIVE_ID):
            raise RuntimeError("PRODSCHED_SHAREPOINT_ENABLED/DRIVE_ID not configured")

        current = None
        try:
            current = graph_client.download_drive_file(
                settings.PRODSCHED_SHAREPOINT_DRIVE_ID,
                settings.PRODSCHED_SHAREPOINT_FILE_PATH,
            )
        except Exception as e:
            logger.error(f"[ProductionSchedule] SharePoint read-back failed: {e}")

        xlsx, result = self._refresh(current)
        sharepoint_url = graph_client.upload_drive_file(
            settings.PRODSCHED_SHAREPOINT_DRIVE_ID,
            settings.PRODSCHED_SHAREPOINT_FILE_PATH,
            xlsx,
        )
        result["sharepoint"] = sharepoint_url or settings.PRODSCHED_SHAREPOINT_WEB_URL or "uploaded"
        logger.info(f"[ProductionSchedule] Refreshed: {result}")
        return result

    def generate_local(self, output_path) -> dict:
        """Local-file variant for manual/dev use — same merge semantics,
        reads and writes a filesystem path instead of SharePoint."""
        from pathlib import Path
        output_path = Path(output_path)
        existing = output_path.read_bytes() if output_path.exists() else None
        xlsx, result = self._refresh(existing)
        output_path.write_bytes(xlsx)
        result["path"] = str(output_path)
        return result


production_schedule_service = ProductionScheduleService()
