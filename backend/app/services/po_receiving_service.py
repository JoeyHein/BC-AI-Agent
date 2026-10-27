"""Receive a released Business Central purchase order.

Joey releases purchase orders in Business Central. This service lists those
released orders, shows ordered / already received / outstanding on each line,
sets Qty. to Receive, and posts Receive only.

The standard purchaseOrders API can patch ``receiveQuantity``. Its only
bound action is ``receiveAndInvoice``, which also creates a purchase invoice.
This service never calls that action. Posting goes through the Receive-only
action on the custom page in ``bc-extension/po-receive``.

Draft purchase orders are not changed here. Requested receipt dates stay on
the draft-only service.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

import requests
from sqlalchemy.orm import Session

from app.db.models import PurchaseReceiptAudit
from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

_QTY = Decimal("0.00001")
_TOLERANCE = Decimal("0.0001")
_VENDOR_SHIPMENT_MAX = 35
_RELEASED_STATUSES = {"open", "released"}
_COMMENT_TYPES = {"comment", ""}

# Shown when BC has not published the Receive-only page.
BC_RECEIVE_SETUP = (
    "Business Central needs a Receive-only action before a receipt can post. "
    "The standard purchaseOrders API only offers Microsoft.NAV.receiveAndInvoice, "
    "and this portal will not call it. Publish page 70910 from "
    "bc-extension/po-receive (API opendc/purchasing/v1.0, entity "
    "purchaseOrderReceives, action receive). Also publish page 50 as the "
    "PurchaseOrder web service so Vendor Shipment No. can be written. "
    "Details are in docs/STAFF_PO_RECEIVING.md."
)


class PoReceiveError(Exception):
    """Mapped to an HTTP error by the purchasing route."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _qty(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value)).quantize(_QTY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _num(value: Decimal) -> float:
    return float(value)


def _is_released(status: Any) -> bool:
    return str(status or "").strip().lower() in _RELEASED_STATUSES


def _is_comment(line: dict) -> bool:
    return str(line.get("lineType") or "").strip().lower() in _COMMENT_TYPES


def _lines_of(po: dict) -> list:
    raw = po.get("purchaseOrderLines") or []
    if isinstance(raw, dict):
        raw = raw.get("value") or []
    return [ln for ln in raw if isinstance(ln, dict)]


def _blank_date(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text or text.startswith("0001-01-01"):
        return None
    return text[:10]


def _item_number(line: dict) -> Optional[str]:
    item = line.get("lineObjectNumber")
    if item is None:
        return None
    text = str(item).strip()
    return text or None


def _outstanding(line: dict) -> Decimal:
    remaining = _qty(line.get("quantity")) - _qty(line.get("receivedQuantity"))
    if remaining < 0:
        return Decimal("0")
    return remaining


def public_line(line: dict, qty_to_receive: Optional[Decimal] = None) -> dict:
    ordered = _qty(line.get("quantity"))
    received = _qty(line.get("receivedQuantity"))
    outstanding = _outstanding(line)
    current = _qty(line.get("receiveQuantity"))
    chosen = current if qty_to_receive is None else qty_to_receive
    return {
        "id": line.get("id"),
        "sequence": line.get("sequence"),
        "line_type": line.get("lineType"),
        "item_number": _item_number(line),
        "description": line.get("description") or "",
        "quantity": _num(ordered),
        "ordered_quantity": _num(ordered),
        "received_quantity": _num(received),
        "outstanding_quantity": _num(outstanding),
        "qty_to_receive": _num(chosen),
        "receive_quantity_on_order": _num(current),
    }


def public_po(po: dict, lines: Optional[list] = None) -> dict:
    shown = lines if lines is not None else [public_line(ln) for ln in _lines_of(po)]
    outstanding_total = sum(ln["outstanding_quantity"] for ln in shown)
    return {
        "bc_po_number": po.get("number"),
        "bc_po_id": po.get("id"),
        "status": po.get("status"),
        "released": _is_released(po.get("status")),
        "vendor_number": po.get("vendorNumber") or None,
        "vendor_name": po.get("vendorName") or po.get("payToVendorName") or None,
        "order_date": _blank_date(po.get("orderDate")),
        "posting_date": _blank_date(po.get("postingDate")),
        "requested_receipt_date": _blank_date(po.get("requestedReceiptDate")),
        "fully_received": outstanding_total <= 0,
        "has_outstanding": outstanding_total > 0,
        "posting": "Receive",
        "invoice": False,
        "lines": shown,
    }


def _not_released_message(number: str, status: Any) -> str:
    shown = status or "unknown"
    return (
        f"{number} is status {shown!r}, which is not released. "
        "Business Central's API reports a released purchase order as Open "
        "(the purchase order page says Released). "
        "Release the purchase order in Business Central before receiving it. "
        "Nothing was posted."
    )


class PoReceivingService:
    def list_released(
        self,
        *,
        number: Optional[str] = None,
        outstanding_only: bool = False,
    ) -> dict:
        try:
            rows = bc_client.get_released_purchase_orders_with_lines()
        except requests.HTTPError as exc:
            raise PoReceiveError(
                502, f"Failed to load released purchase orders from Business Central: {exc}",
            ) from exc
        wanted = (number or "").strip().upper()
        purchase_orders = []
        for po in rows:
            if not _is_released(po.get("status")):
                continue
            if wanted and str(po.get("number") or "").upper() != wanted:
                continue
            body = public_po(po)
            if outstanding_only and not body["has_outstanding"]:
                continue
            purchase_orders.append(body)
        purchase_orders.sort(key=lambda row: row.get("bc_po_number") or "")
        return {"count": len(purchase_orders), "purchase_orders": purchase_orders}

    def get_released(self, kind: str, value: str) -> dict:
        po = self._load(kind, value)
        self._require_released(po, value)
        return public_po(po)

    def receive(self, db: Session, kind: str, value: str, body: dict, actor: dict) -> dict:
        """Preview or post a Receive-only receipt.

        ``dry_run`` defaults to true at the route. A preview validates and
        returns the lines that would post, and does not write to Business
        Central. A post sets Qty. to Receive, writes the vendor packing slip,
        then calls the Receive-only action.
        """
        po = self._load(kind, value)
        number = po.get("number") or value
        try:
            self._require_released(po, number)
            slip = self._packing_slip(body)
            plan = self._plan(po, body.get("lines") or [])
        except PoReceiveError as exc:
            self._reject_audit(db, po, body, actor, exc)
            raise
        dry_run = bool(body.get("dry_run", True))
        preview = self._preview(po, plan, slip, dry_run=dry_run, posted=False)

        audit_id = self._start_audit(
            db,
            po=po,
            slip=slip,
            receiving=preview["receiving"],
            actor=actor,
            dry_run=dry_run,
            outcome="dry_run" if dry_run else "pending",
        )
        preview["audit_id"] = audit_id

        if dry_run:
            logger.info(
                "PO receive preview actor=%s po=%s slip=%s lines=%s",
                actor.get("actor_name"), number, slip, preview["receiving"],
            )
            return preview

        try:
            self._apply(po, plan, slip, number)
        except PoReceiveError as exc:
            self._finish_audit(db, audit_id, outcome="bc_error", posted=False, error=exc.detail)
            raise
        receipt_no = self._posted_receipt_no(po)
        fresh = self._reload(po) or po
        shown_plan = dict(plan)
        shown_plan["lines"] = _lines_of(fresh) or plan["lines"]
        result = self._preview(fresh, shown_plan, slip, dry_run=False, posted=True)
        result["bc_receipt_no"] = receipt_no
        result["audit_id"] = audit_id
        try:
            self._finish_audit(
                db,
                audit_id,
                outcome="posted",
                posted=True,
                bc_receipt_no=receipt_no,
                error=None,
            )
        except Exception:
            logger.exception("Receipt for %s posted but the audit row could not be updated", number)
            result["audit_logged"] = False
        logger.info(
            "PO receive posted actor=%s po=%s slip=%s receipt=%s lines=%s",
            actor.get("actor_name"), number, slip, receipt_no, result["receiving"],
        )
        return result

    # ── planning ────────────────────────────────────────────────

    def _plan(self, po: dict, requested: list) -> dict:
        if not isinstance(requested, list) or not requested:
            raise PoReceiveError(400, "Send at least one line to receive")
        lines = _lines_of(po)
        by_id = {str(ln.get("id")): ln for ln in lines if ln.get("id")}
        chosen: dict[str, Decimal] = {}
        for raw in requested:
            if not isinstance(raw, dict):
                raise PoReceiveError(400, "Each line must be an object")
            line = self._match_line(po, lines, raw)
            line_id = str(line.get("id"))
            if line_id in chosen:
                raise PoReceiveError(400, f"Line {line_id} was sent more than once")
            qty = self._requested_qty(raw)
            if qty < 0:
                raise PoReceiveError(400, "qty_to_receive cannot be negative")
            if qty == 0:
                continue
            if _is_comment(line):
                raise PoReceiveError(
                    422,
                    f"Line {line.get('sequence')} is a comment and cannot be received",
                )
            outstanding = _outstanding(line)
            if qty - outstanding > _TOLERANCE:
                item = _item_number(line) or line.get("description") or line_id
                raise PoReceiveError(
                    422,
                    f"Line {line.get('sequence')} ({item}) qty_to_receive {_num(qty)} "
                    f"is above outstanding {_num(outstanding)} "
                    f"(ordered {_num(_qty(line.get('quantity')))}, "
                    f"already received {_num(_qty(line.get('receivedQuantity')))}).",
                )
            chosen[line_id] = qty

        if not chosen:
            raise PoReceiveError(400, "Send a qty_to_receive greater than zero")

        updates = []
        clears = []
        for line in lines:
            line_id = str(line.get("id") or "")
            if not line_id or _is_comment(line):
                continue
            if line_id in chosen:
                updates.append({
                    "id": line_id,
                    "receiveQuantity": _num(chosen[line_id]),
                    "invoiceQuantity": 0,
                })
            elif _qty(line.get("receiveQuantity")) > _TOLERANCE:
                clears.append({"id": line_id, "receiveQuantity": 0})
        return {"chosen": chosen, "updates": updates, "clears": clears, "lines": lines}

    def _match_line(self, po: dict, lines: list, raw: dict) -> dict:
        number = po.get("number") or "purchase order"
        line_id = str(raw.get("line_id") or raw.get("id") or "").strip()
        sequence = raw.get("sequence")
        item = str(raw.get("item_number") or raw.get("item_no") or "").strip()
        if line_id:
            match = next((ln for ln in lines if str(ln.get("id")) == line_id), None)
            if match is None:
                raise PoReceiveError(422, f"Line {line_id} is not on {number}")
            if item and (_item_number(match) or "").lower() != item.lower():
                raise PoReceiveError(
                    422,
                    f"Line {line_id} on {number} is item {_item_number(match)}, not {item}",
                )
            return match
        if sequence is not None and sequence != "":
            try:
                wanted = int(sequence)
            except (TypeError, ValueError):
                raise PoReceiveError(400, "sequence must be a line number")
            matches = [ln for ln in lines if ln.get("sequence") == wanted]
            if not matches:
                raise PoReceiveError(422, f"Line sequence {wanted} is not on {number}")
            if item and (_item_number(matches[0]) or "").lower() != item.lower():
                raise PoReceiveError(
                    422,
                    f"Line {wanted} on {number} is item {_item_number(matches[0])}, not {item}",
                )
            return matches[0]
        if not item:
            raise PoReceiveError(400, "Each line needs a line_id, sequence, or item_number")
        matches = [
            ln for ln in lines
            if (_item_number(ln) or "").lower() == item.lower()
        ]
        if not matches:
            raise PoReceiveError(422, f"Item {item} is not on {number}")
        if len(matches) > 1:
            raise PoReceiveError(
                422,
                f"Item {item} is on more than one line of {number}. Send line_id or sequence.",
            )
        return matches[0]

    def _requested_qty(self, raw: dict) -> Decimal:
        if "qty_to_receive" not in raw:
            raise PoReceiveError(400, "Each line needs qty_to_receive")
        value = raw.get("qty_to_receive")
        if isinstance(value, bool) or value is None:
            raise PoReceiveError(400, "qty_to_receive must be a number")
        try:
            qty = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise PoReceiveError(400, "qty_to_receive must be a number")
        if qty < 0:
            return qty
        rounded = qty.quantize(_QTY, rounding=ROUND_HALF_UP)
        if abs(qty - rounded) > Decimal("0.0000001"):
            raise PoReceiveError(400, "qty_to_receive supports up to 5 decimal places")
        return rounded

    def _packing_slip(self, body: dict) -> str:
        primary = body.get("vendor_shipment_no")
        alias = body.get("vendor_packing_slip")
        left = "" if primary is None else str(primary).strip()
        right = "" if alias is None else str(alias).strip()
        if left and right and left != right:
            raise PoReceiveError(
                400,
                "vendor_shipment_no and vendor_packing_slip must be the same value",
            )
        slip = left or right
        if not slip:
            raise PoReceiveError(
                400,
                "vendor_shipment_no is required (the vendor packing slip)",
            )
        if len(slip) > _VENDOR_SHIPMENT_MAX or any(ch in slip for ch in "\r\n"):
            raise PoReceiveError(
                400,
                f"vendor_shipment_no must be a single line of at most {_VENDOR_SHIPMENT_MAX} characters",
            )
        return slip

    def _preview(self, po: dict, plan: dict, slip: str, *, dry_run: bool, posted: bool) -> dict:
        chosen = plan["chosen"]
        shown = []
        receiving = []
        for line in plan["lines"]:
            line_id = str(line.get("id") or "")
            qty = chosen.get(line_id, Decimal("0"))
            row = public_line(line, qty_to_receive=qty)
            shown.append(row)
            if line_id in chosen:
                receiving.append(row)
        body = public_po(po, shown)
        body.update({
            "dry_run": dry_run,
            "posted": posted,
            "vendor_shipment_no": slip,
            "receiving": receiving,
            "lines_to_clear": plan["clears"],
            "bc_receipt_no": None,
        })
        return body

    # ── Business Central ────────────────────────────────────────

    def _apply(self, po: dict, plan: dict, slip: str, number: str) -> None:
        po_id = po.get("id")
        if not po_id:
            raise PoReceiveError(502, f"{number} has no Business Central id")
        try:
            bc_client.set_purchase_order_vendor_shipment_no(number, slip)
        except (requests.HTTPError, LookupError, RuntimeError, ValueError) as exc:
            raise PoReceiveError(
                502,
                f"Could not set Vendor Shipment No. on {number}: {exc}. {BC_RECEIVE_SETUP}",
            ) from exc

        applied: list[tuple[str, dict]] = []
        try:
            for patch in plan["updates"] + plan["clears"]:
                line_id = patch["id"]
                previous = self._line_snapshot(plan["lines"], line_id)
                payload = {key: patch[key] for key in patch if key != "id"}
                bc_client.update_purchase_order_line(po_id, line_id, payload)
                applied.append((line_id, previous))
        except (requests.HTTPError, RuntimeError) as exc:
            self._restore(po_id, applied)
            raise PoReceiveError(
                502, f"Could not set Qty. to Receive on {number}: {exc}",
            ) from exc

        try:
            bc_client.post_purchase_order_receive(po_id)
        except RuntimeError as exc:
            self._restore(po_id, applied)
            raise PoReceiveError(502, f"{exc} {BC_RECEIVE_SETUP}") from exc
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            # 5xx can mean the receipt committed and the response failed.
            # Leave Qty. to Receive as posted and tell the caller to look in BC.
            if status is None or status >= 500:
                raise PoReceiveError(
                    502,
                    f"Business Central may have posted {number} but returned an error: {exc}. "
                    "Check the purchase order in Business Central before sending this receipt again.",
                ) from exc
            self._restore(po_id, applied)
            raise PoReceiveError(
                502,
                f"Business Central did not post the receipt for {number}: {exc}. {BC_RECEIVE_SETUP}",
            ) from exc

    def _line_snapshot(self, lines: list, line_id: str) -> dict:
        line = next((ln for ln in lines if str(ln.get("id")) == line_id), {})
        return {
            "receiveQuantity": _num(_qty(line.get("receiveQuantity"))),
            "invoiceQuantity": _num(_qty(line.get("invoiceQuantity"))),
        }

    def _restore(self, po_id: str, applied: list) -> None:
        for line_id, previous in reversed(applied):
            try:
                bc_client.update_purchase_order_line(po_id, line_id, previous)
            except requests.HTTPError:
                logger.warning(
                    "Could not restore qty to receive on %s line %s", po_id, line_id,
                    exc_info=True,
                )

    def _posted_receipt_no(self, po: dict) -> Optional[str]:
        header = {}
        try:
            header = bc_client.get_purchase_order_receive_header(po.get("id")) or {}
        except (requests.HTTPError, RuntimeError, ValueError):
            header = {}
        last = header.get("lastReceivingNo") or header.get("last_receiving_no")
        if last:
            return str(last)
        try:
            receipts = bc_client.list_purchase_receipts_for_order(po.get("number") or "")
        except requests.HTTPError:
            logger.warning("Could not list purchase receipts for %s", po.get("number"), exc_info=True)
            return None
        if not receipts:
            return None
        receipts = sorted(
            receipts,
            key=lambda row: (str(row.get("postingDate") or ""), str(row.get("number") or "")),
        )
        number = receipts[-1].get("number")
        return str(number) if number else None

    def _load(self, kind: str, value: str) -> dict:
        try:
            if kind == "guid":
                po = bc_client.get_purchase_order_with_lines(value)
            else:
                po = bc_client.get_purchase_order_by_number(value)
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 404:
                raise PoReceiveError(404, f"Purchase order {value} not found") from exc
            raise PoReceiveError(
                502, f"Failed to load purchase order {value} from Business Central: {exc}",
            ) from exc
        if not po:
            raise PoReceiveError(404, f"Purchase order {value} not found")
        return po

    def _reload(self, po: dict) -> Optional[dict]:
        po_id = po.get("id")
        if not po_id:
            return None
        try:
            return bc_client.get_purchase_order_with_lines(po_id)
        except requests.HTTPError:
            logger.warning("Could not reload purchase order %s after receipt", po.get("number"))
            return None

    def _require_released(self, po: dict, number: str) -> None:
        if not _is_released(po.get("status")):
            raise PoReceiveError(422, _not_released_message(po.get("number") or number, po.get("status")))

    # ── audit ───────────────────────────────────────────────────

    def _reject_audit(self, db: Session, po: dict, body: dict, actor: dict, exc: PoReceiveError) -> None:
        """Record a receipt that failed validation. Does not hide the original error."""
        slip = ""
        try:
            slip = self._packing_slip(body)
        except PoReceiveError:
            raw = body.get("vendor_shipment_no") or body.get("vendor_packing_slip") or ""
            slip = str(raw).strip()[:_VENDOR_SHIPMENT_MAX]
        try:
            self._start_audit(
                db,
                po=po,
                slip=slip,
                receiving=body.get("lines") or [],
                actor=actor,
                dry_run=bool(body.get("dry_run", True)),
                outcome="rejected",
                error=exc.detail,
            )
        except Exception:
            logger.warning("Could not audit rejected receipt for %s", po.get("number"), exc_info=True)
            db.rollback()

    def _start_audit(
        self,
        db: Session,
        *,
        po: dict,
        slip: str,
        receiving: list,
        actor: dict,
        dry_run: bool,
        outcome: str,
        error: Optional[str] = None,
    ) -> int:
        row = PurchaseReceiptAudit(
            user_id=actor.get("user_id"),
            actor_email=actor.get("actor_email"),
            actor_name=actor.get("actor_name"),
            service_key_id=actor.get("service_key_id"),
            service_key_name=actor.get("service_key_name"),
            po_number=po.get("number") or "",
            po_id=po.get("id"),
            vendor_number=po.get("vendorNumber"),
            vendor_name=po.get("vendorName") or po.get("payToVendorName"),
            vendor_shipment_no=slip,
            lines=receiving,
            dry_run=dry_run,
            posted=False,
            posting="Receive",
            invoice=False,
            outcome=outcome,
            error=error,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id

    def _finish_audit(self, db: Session, audit_id: int, **fields) -> None:
        row = db.query(PurchaseReceiptAudit).filter(PurchaseReceiptAudit.id == audit_id).one()
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


po_receiving_service = PoReceivingService()
