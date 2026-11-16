"""Receive selected lines on one Business Central purchase order.

Nothing else in the portal calls this. The staff route is the only caller.
A real receipt requires ``confirm: true``. ``dry_run`` checks quantities and
does not post.

The standard api/v2.0 action ``receiveAndInvoice`` is not used. That action
sets Invoice as well as Receive, and the combined post invoices the quantity
just received. Posting goes through page 70152 "OPENDC API PO Receive", which
calls Purch.-Post with Receive true and Invoice false. The page does not
send email.

API status Draft is Business Central document status Open. Posting requires
Released, so the page releases an Open order first. API status Open, and a
literal Released, are already released and are received without a second
release. In Review (pending approval) is refused.

``line_no`` is Purchase Line "Line No.", the ``sequence`` value on
purchaseOrders lines (10000, 20000, …). Lines not listed are posted with
Qty. to Receive = 0.

When ``vendor_shipment_no`` is set, a second call for the same purchase
order and packing slip returns the posted receipt and does not post again.
The number is stored uppercase, which is how Business Central stores a Code
field. Omit it and each call posts.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, List, Optional, Sequence

import requests
from sqlalchemy.orm import Session

from app.db.models import AuditTrail
from app.integrations.bc.client import (
    PURCHASE_ORDER_RECEIVE_ACTION,
    PurchaseOrderReceiveNotPublished,
    bc_client,
)

logger = logging.getLogger(__name__)

_RECEIVABLE_STATUSES = frozenset({"draft", "open", "released"})
_RELEASED_API_STATUSES = frozenset({"open", "released"})
_PRIOR_ACTIONS = (
    "purchase_order_receive_received",
    "purchase_order_receive_idempotent",
)
_MAX_LINES = 200
_SHIPMENT_MAX = 35
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict = {}

_PUBLISH_HINT = (
    "Business Central's api/v2.0 purchaseOrders entity cannot receive without "
    "invoicing (its only bound action is receiveAndInvoice, which sets Invoice "
    "as well as Receive). Publish page 70152 \"OPENDC API PO Receive\" from "
    "bc-extension/purchase-order-receive in the same extension as page 70150 "
    "(API publisher opendc, group purchasing, version v1.0) and assign "
    "permission set \"OPENDC PO Receive\" to the integration user, on top of "
    "the permissions that user needs to post a purchase receipt. "
    "See docs/STAFF_PO_RECEIVE.md."
)


class PurchaseOrderReceiveError(Exception):
    """Mapped to HTTP by the route. ``detail`` is a string or a dict."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        super().__init__(message)


def _lock_for(number: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(number)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[number] = lock
        return lock


def _dec(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise InvalidOperation
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value).strip())


def _json_qty(value: Decimal) -> Any:
    integral = value.to_integral_value()
    if value == integral:
        return int(integral)
    return float(value)


def _line_no(line: dict) -> Optional[int]:
    for key in ("sequence", "lineNumber", "lineNo"):
        raw = line.get(key)
        if raw is None or raw == "":
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        return number
    return None


def _outstanding(line: dict) -> Decimal:
    quantity = _dec(line.get("quantity") or 0)
    received_raw = line.get("receivedQuantity")
    if received_raw is None:
        received_raw = line.get("received_quantity") or 0
    received = _dec(received_raw or 0)
    remaining = quantity - received
    if remaining < 0:
        return Decimal(0)
    return remaining


def _normalize_shipment(raw: Optional[str]) -> str:
    text = (raw or "").strip().upper()
    if not text:
        return ""
    if len(text) > _SHIPMENT_MAX:
        raise PurchaseOrderReceiveError(422, {
            "message": (
                f"vendor_shipment_no is longer than {_SHIPMENT_MAX} characters. "
                "Nothing was posted."
            ),
            "posted": False,
            "invoiced": False,
            "emailed": False,
            "reasons": [{
                "code": "vendor_shipment_no_too_long",
                "severity": "error",
                "message": (
                    f"Vendor shipment numbers are {_SHIPMENT_MAX} characters in "
                    "Business Central. Nothing was posted."
                ),
            }],
        })
    return text


def _normalize_request_lines(lines: Optional[Sequence[dict]]) -> List[dict]:
    if not lines:
        return []
    if len(lines) > _MAX_LINES:
        raise PurchaseOrderReceiveError(422, {
            "message": f"At most {_MAX_LINES} lines can be received in one call. Nothing was posted.",
            "posted": False,
            "invoiced": False,
            "emailed": False,
            "reasons": [{
                "code": "too_many_lines",
                "severity": "error",
                "message": f"Send at most {_MAX_LINES} lines.",
            }],
        })
    cleaned: List[dict] = []
    seen = set()
    reasons: List[dict] = []
    for raw in lines:
        if not isinstance(raw, dict):
            reasons.append({
                "code": "line_invalid",
                "severity": "error",
                "message": "Each line must be an object with line_no and qty.",
            })
            continue
        try:
            line_no = int(raw.get("line_no"))
        except (TypeError, ValueError):
            reasons.append({
                "code": "line_no_invalid",
                "severity": "error",
                "message": "line_no must be the purchase line number (sequence), such as 10000.",
            })
            continue
        if line_no <= 0:
            reasons.append({
                "code": "line_no_invalid",
                "severity": "error",
                "line_no": line_no,
                "message": "line_no must be greater than zero.",
            })
            continue
        if line_no in seen:
            reasons.append({
                "code": "duplicate_line",
                "severity": "error",
                "line_no": line_no,
                "message": f"Line {line_no} is listed more than once. Nothing was posted.",
            })
            continue
        seen.add(line_no)
        try:
            qty = _dec(raw.get("qty"))
        except (InvalidOperation, ValueError):
            reasons.append({
                "code": "qty_invalid",
                "severity": "error",
                "line_no": line_no,
                "message": f"Line {line_no} needs a quantity greater than zero.",
            })
            continue
        if qty <= 0:
            reasons.append({
                "code": "qty_invalid",
                "severity": "error",
                "line_no": line_no,
                "qty": _json_qty(qty) if qty == qty else None,
                "message": f"Line {line_no} quantity must be greater than zero. Nothing was posted.",
            })
            continue
        cleaned.append({"line_no": line_no, "qty": qty})
    if reasons:
        raise PurchaseOrderReceiveError(422, {
            "message": "These lines cannot be received. Nothing was posted.",
            "posted": False,
            "invoiced": False,
            "emailed": False,
            "reasons": reasons,
        })
    return cleaned


def _lines_json(lines: Sequence[dict]) -> str:
    parts = []
    for line in lines:
        parts.append(
            '{"lineNo":%d,"qty":%s}' % (int(line["line_no"]), format(line["qty"], "f"))
        )
    return "[" + ",".join(parts) + "]"


def _bc_client_status(message: str) -> int:
    text = (message or "").lower()
    if any(token in text for token in ("receive:qty", "receive:line", "receive:status", "receive:lines")):
        return 422
    return 502


def _receipt_no(body: Optional[dict]) -> str:
    if not isinstance(body, dict):
        return ""
    return str(body.get("postedReceiptNo") or "").strip()


def _index_lines(po: dict) -> dict:
    indexed = {}
    for line in po.get("purchaseOrderLines") or []:
        number = _line_no(line)
        if number is None or number in indexed:
            continue
        indexed[number] = line
    return indexed


def assess_receipt(po: dict, lines: Sequence[dict]) -> dict:
    """Quantity checks for one PO. Does not call Business Central posting."""
    status = str(po.get("status") or "")
    blocking: List[dict] = []
    if status.casefold() not in _RECEIVABLE_STATUSES:
        shown = status or "(blank)"
        blocking.append({
            "code": "not_receivable_status",
            "severity": "error",
            "message": (
                f"{po.get('number') or 'This purchase order'} is status {shown!r}. "
                "Only Draft, Open, or Released can be received. In Review means "
                "the order is pending approval. Nothing was posted."
            ),
        })

    indexed = _index_lines(po)
    planned: List[dict] = []
    requested = set()
    if not lines and not blocking:
        blocking.append({
            "code": "lines_required",
            "severity": "error",
            "message": "Send at least one line with line_no and qty. Nothing was posted.",
        })
    for line in lines:
        line_no = int(line["line_no"])
        qty = line["qty"]
        requested.add(line_no)
        source = indexed.get(line_no)
        if source is None:
            blocking.append({
                "code": "unknown_line",
                "severity": "error",
                "line_no": line_no,
                "message": (
                    f"Purchase order {po.get('number') or ''} has no line {line_no}. "
                    "line_no is the line sequence from the purchase order (10000, 20000, …). "
                    "Nothing was posted."
                ),
            })
            continue
        line_type = str(source.get("lineType") or "")
        outstanding = _outstanding(source)
        if line_type.casefold() == "comment" or line_type.strip() == "":
            blocking.append({
                "code": "not_receivable_line",
                "severity": "error",
                "line_no": line_no,
                "message": f"Line {line_no} is a {line_type or 'blank'} line and cannot be received.",
            })
            continue
        if qty > outstanding:
            blocking.append({
                "code": "qty_exceeds_outstanding",
                "severity": "error",
                "line_no": line_no,
                "qty": _json_qty(qty),
                "outstanding": _json_qty(outstanding),
                "message": (
                    f"Line {line_no} quantity {_json_qty(qty)} exceeds outstanding "
                    f"{_json_qty(outstanding)}. Nothing was posted."
                ),
            })
            continue
        planned.append({
            "line_no": line_no,
            "qty": _json_qty(qty),
            "outstanding": _json_qty(outstanding),
            "outstanding_after": _json_qty(outstanding - qty),
            "item_no": source.get("lineObjectNumber") or "",
            "description": source.get("description") or "",
            "line_type": line_type,
        })

    untouched: List[dict] = []
    for line_no, source in sorted(indexed.items()):
        if line_no in requested:
            continue
        line_type = str(source.get("lineType") or "")
        if line_type.casefold() == "comment":
            continue
        untouched.append({
            "line_no": line_no,
            "qty_to_receive": 0,
            "outstanding": _json_qty(_outstanding(source)),
            "item_no": source.get("lineObjectNumber") or "",
            "description": source.get("description") or "",
        })

    return {
        "blocking": blocking,
        "lines": planned,
        "untouched_lines": untouched,
        "would_release": status.casefold() == "draft" and not blocking,
        "api_status": status,
    }


class PurchaseOrderReceiveService:
    def receive(
        self,
        kind: str,
        value: str,
        *,
        lines: Sequence[dict],
        vendor_shipment_no: str,
        confirm: bool,
        dry_run: bool,
        actor: str,
        service_key_name: Optional[str],
        db: Session,
    ) -> dict:
        shipment = _normalize_shipment(vendor_shipment_no)
        request_lines = _normalize_request_lines(lines)
        who = (actor or "").strip() or "staff"

        try:
            po = self._load(kind, value)
        except PurchaseOrderReceiveError as exc:
            if exc.status_code == 404 and shipment and kind == "number":
                prior = self._prior(db, value, shipment)
                if prior is not None:
                    return self._already(
                        db, po={"number": value, "id": None, "status": None},
                        shipment=shipment, prior=prior, actor=who,
                        service_key_name=service_key_name, source="audit",
                        dry_run=dry_run,
                        confirm=confirm,
                    )
            raise

        number = str(po.get("number") or value)
        with _lock_for(number):
            fresh = self._load(kind, value)
            return self._receive_locked(
                fresh,
                request_lines=request_lines,
                shipment=shipment,
                confirm=confirm,
                dry_run=dry_run,
                actor=who,
                service_key_name=service_key_name,
                db=db,
            )

    def _receive_locked(
        self,
        po: dict,
        *,
        request_lines: List[dict],
        shipment: str,
        confirm: bool,
        dry_run: bool,
        actor: str,
        service_key_name: Optional[str],
        db: Session,
    ) -> dict:
        number = str(po.get("number") or "")
        status = str(po.get("status") or "")
        if shipment:
            prior = self._prior(db, number, shipment)
            if prior is not None:
                return self._already(
                    db, po=po, shipment=shipment, prior=prior, actor=actor,
                    service_key_name=service_key_name, source="audit", dry_run=dry_run,
                    confirm=confirm,
                )

        lookup_warning = None
        existing = None
        unpublished = False
        if shipment:
            existing, lookup_warning, unpublished = self._lookup_bc(po, shipment)

        if existing is not None:
            return self._already(
                db, po=po, shipment=shipment, prior={
                    "posted_receipt_no": _receipt_no(existing),
                    "posted_receipt_id": existing.get("postedReceiptId"),
                    "lines": [],
                }, actor=actor, service_key_name=service_key_name,
                source="business_central", dry_run=dry_run, confirm=confirm,
            )

        assessment = assess_receipt(po, request_lines)
        blocking = assessment["blocking"]
        warnings = [lookup_warning] if lookup_warning else []

        if dry_run:
            logged = self._audit(
                db, actor=actor, service_key_name=service_key_name, confirm=confirm,
                dry_run=True, po=po, shipment=shipment, outcome="dry_run",
                reasons=blocking, warnings=warnings, lines=assessment["lines"],
            )
            would = not blocking
            return {
                "dry_run": True,
                "posted": False,
                "would_post": would,
                "would_release": assessment["would_release"],
                "idempotent": False,
                "invoiced": False,
                "emailed": False,
                "bc_post_called": False,
                "number": number,
                "api_status": status,
                "vendor_shipment_no": shipment or None,
                "lines": assessment["lines"],
                "untouched_lines": assessment["untouched_lines"],
                "reasons": blocking,
                "warnings": warnings,
                "message": (
                    f"{number} would post a receipt for {len(assessment['lines'])} line(s). "
                    "Nothing was posted."
                    if would
                    else f"{number} would not be received. Nothing was posted."
                ),
                "audit_logged": logged,
            }

        if blocking:
            detail = self._refused(number, status, shipment, blocking, warnings, assessment)
            detail["audit_logged"] = self._audit(
                db, actor=actor, service_key_name=service_key_name, confirm=confirm,
                dry_run=False, po=po, shipment=shipment, outcome="refused",
                reasons=blocking, warnings=warnings, lines=assessment["lines"],
            )
            raise PurchaseOrderReceiveError(422, detail)

        if confirm is not True:
            reasons = [{
                "code": "confirm_required",
                "severity": "error",
                "message": (
                    "Set confirm to true to receive this purchase order. "
                    "Nothing was posted."
                ),
            }]
            detail = self._refused(number, status, shipment, reasons, warnings, assessment)
            detail["audit_logged"] = self._audit(
                db, actor=actor, service_key_name=service_key_name, confirm=confirm,
                dry_run=False, po=po, shipment=shipment, outcome="refused",
                reasons=reasons, warnings=warnings, lines=assessment["lines"],
            )
            raise PurchaseOrderReceiveError(422, detail)

        if unpublished:
            message = _PUBLISH_HINT
            self._audit(
                db, actor=actor, service_key_name=service_key_name, confirm=True,
                dry_run=False, po=po, shipment=shipment, outcome="bc_unavailable",
                reasons=[{"code": "receive_action_not_published", "message": message}],
                warnings=warnings, lines=assessment["lines"],
            )
            raise PurchaseOrderReceiveError(502, message)

        po_id = po.get("id")
        if not po_id:
            raise PurchaseOrderReceiveError(
                502, f"{number} has no Business Central system id, so it cannot be received.",
            )

        logger.info(
            "Admin %s receiving %s lines=%s shipment=%s",
            actor, number, [row["line_no"] for row in request_lines], shipment or "-",
        )
        try:
            body = bc_client.receive_purchase_order(po_id, shipment, _lines_json(request_lines))
        except PurchaseOrderReceiveNotPublished as exc:
            message = f"{_PUBLISH_HINT} Business Central said: {exc}"
            self._audit(
                db, actor=actor, service_key_name=service_key_name, confirm=True,
                dry_run=False, po=po, shipment=shipment, outcome="bc_unavailable",
                reasons=[{"code": "receive_action_not_published", "message": message}],
                warnings=warnings, lines=assessment["lines"],
            )
            raise PurchaseOrderReceiveError(502, message) from exc
        except requests.HTTPError as exc:
            message = str(exc)
            status_code = _bc_client_status(message)
            self._audit(
                db, actor=actor, service_key_name=service_key_name, confirm=True,
                dry_run=False, po=po, shipment=shipment,
                outcome="refused" if status_code == 422 else "bc_error",
                reasons=[{"code": "bc_rejected", "message": message}],
                warnings=warnings, lines=assessment["lines"],
            )
            if status_code == 422:
                raise PurchaseOrderReceiveError(422, {
                    "message": message,
                    "number": number,
                    "posted": False,
                    "invoiced": False,
                    "emailed": False,
                    "reasons": [{"code": "bc_rejected", "severity": "error", "message": message}],
                }) from exc
            raise PurchaseOrderReceiveError(
                502, f"Business Central rejected the receipt for {number}: {message}",
            ) from exc

        if body.get("invoiced") is True:
            message = (
                f"Business Central reported an invoice while receiving {number}. "
                "This endpoint does not invoice. Check the order before trying again."
            )
            self._audit(
                db, actor=actor, service_key_name=service_key_name, confirm=True,
                dry_run=False, po=po, shipment=shipment, outcome="bc_error",
                reasons=[{"code": "invoiced", "message": message}],
                warnings=warnings, lines=assessment["lines"],
            )
            raise PurchaseOrderReceiveError(502, {
                "message": message,
                "number": number,
                "posted": False,
                "invoiced": True,
                "emailed": False,
            })

        if body.get("idempotent") is True and _receipt_no(body):
            return self._already(
                db, po=po, shipment=shipment, prior={
                    "posted_receipt_no": _receipt_no(body),
                    "posted_receipt_id": body.get("postedReceiptId"),
                    "lines": assessment["lines"],
                }, actor=actor, service_key_name=service_key_name,
                source="business_central", dry_run=False, confirm=True,
            )

        receipt = _receipt_no(body)
        if not receipt:
            receipt = str(body.get("lastReceivingNo") or "").strip()
        if not receipt:
            message = (
                f"Business Central accepted the receive call for {number}, but "
                "it did not return a posted receipt number. Check posted receipts "
                "for this order before trying again. Nothing further was posted by the portal."
            )
            self._audit(
                db, actor=actor, service_key_name=service_key_name, confirm=True,
                dry_run=False, po=po, shipment=shipment, outcome="unconfirmed",
                reasons=[{"code": "receipt_unconfirmed", "message": message}],
                warnings=warnings, lines=assessment["lines"],
            )
            raise PurchaseOrderReceiveError(502, {
                "message": message,
                "number": number,
                "posted": False,
                "invoiced": False,
                "emailed": False,
                "bc_post_called": True,
            })

        released = bool(body.get("releasedForReceipt")) or status.casefold() == "draft"
        logged = self._audit(
            db, actor=actor, service_key_name=service_key_name, confirm=True,
            dry_run=False, po=po, shipment=shipment, outcome="received",
            reasons=[], warnings=warnings, lines=assessment["lines"],
            posted_receipt_no=receipt,
            posted_receipt_id=body.get("postedReceiptId"),
            released_for_receipt=released,
        )
        return {
            "dry_run": False,
            "posted": True,
            "would_post": False,
            "idempotent": False,
            "invoiced": False,
            "emailed": False,
            "bc_post_called": True,
            "released": released,
            "number": number,
            "id": po_id,
            "api_status_before": status,
            "bc_document_status_before": (
                "Open" if status.casefold() == "draft" else "Released"
                if status.casefold() in _RELEASED_API_STATUSES else status
            ),
            "posted_receipt_no": receipt,
            "posted_receipt_id": body.get("postedReceiptId"),
            "vendor_shipment_no": shipment or None,
            "lines": assessment["lines"],
            "untouched_lines": assessment["untouched_lines"],
            "warnings": warnings,
            "bc_action": PURCHASE_ORDER_RECEIVE_ACTION,
            "message": (
                f"{number} receipt {receipt} is posted. "
                "The order was not invoiced and no vendor email was sent."
            ),
            "audit_logged": logged,
        }

    def _lookup_bc(self, po: dict, shipment: str):
        po_id = po.get("id")
        if not po_id:
            return None, None, False
        try:
            body = bc_client.find_posted_purchase_receipt(po_id, shipment)
        except PurchaseOrderReceiveNotPublished as exc:
            return None, {
                "code": "receipt_lookup_unavailable",
                "severity": "warning",
                "message": (
                    "The receive page is not published, so an existing packing "
                    f"slip could not be checked in Business Central. {exc}"
                ),
            }, True
        except requests.HTTPError as exc:
            raise PurchaseOrderReceiveError(
                502, f"Business Central could not look up receipts for {po.get('number')}: {exc}",
            ) from exc
        if _receipt_no(body):
            return body, None, False
        return None, None, False

    def _already(
        self,
        db: Session,
        *,
        po: dict,
        shipment: str,
        prior: dict,
        actor: str,
        service_key_name: Optional[str],
        source: str,
        dry_run: bool,
        confirm: bool,
    ) -> dict:
        number = str(po.get("number") or "")
        receipt = str(prior.get("posted_receipt_no") or "")
        if dry_run:
            logged = self._audit(
                db, actor=actor, service_key_name=service_key_name, confirm=confirm,
                dry_run=True, po=po, shipment=shipment, outcome="dry_run",
                reasons=[], warnings=[], lines=prior.get("lines") or [],
                posted_receipt_no=receipt,
                posted_receipt_id=prior.get("posted_receipt_id"),
            )
            return {
                "dry_run": True,
                "posted": False,
                "would_post": False,
                "idempotent": True,
                "invoiced": False,
                "emailed": False,
                "bc_post_called": False,
                "number": number,
                "posted_receipt_no": receipt,
                "posted_receipt_id": prior.get("posted_receipt_id"),
                "vendor_shipment_no": shipment,
                "source": source,
                "message": (
                    f"{number} was already received against vendor shipment {shipment} "
                    f"({receipt}). Nothing would be posted."
                ),
                "audit_logged": logged,
            }
        return self._idempotent(
            db, po=po, shipment=shipment, prior=prior, actor=actor,
            service_key_name=service_key_name, source=source, confirm=confirm,
        )

    def _idempotent(
        self,
        db: Session,
        *,
        po: dict,
        shipment: str,
        prior: dict,
        actor: str,
        service_key_name: Optional[str],
        source: str,
        confirm: bool,
    ) -> dict:
        number = str(po.get("number") or "")
        receipt = str(prior.get("posted_receipt_no") or "")
        logged = self._audit(
            db, actor=actor, service_key_name=service_key_name, confirm=confirm,
            dry_run=False, po=po, shipment=shipment, outcome="idempotent",
            reasons=[], warnings=[], lines=prior.get("lines") or [],
            posted_receipt_no=receipt,
            posted_receipt_id=prior.get("posted_receipt_id"),
            released_for_receipt=bool(prior.get("released_for_receipt")),
        )
        return {
            "dry_run": False,
            "posted": False,
            "would_post": False,
            "idempotent": True,
            "invoiced": False,
            "emailed": False,
            "bc_post_called": False,
            "number": number,
            "posted_receipt_no": receipt,
            "posted_receipt_id": prior.get("posted_receipt_id"),
            "vendor_shipment_no": shipment,
            "lines": prior.get("lines") or [],
            "source": source,
            "message": (
                f"{number} was already received against vendor shipment {shipment} "
                f"({receipt}). Nothing was posted."
            ),
            "audit_logged": logged,
        }

    def _refused(self, number, status, shipment, reasons, warnings, assessment) -> dict:
        return {
            "message": reasons[0]["message"] if reasons else f"{number} cannot be received.",
            "number": number,
            "api_status": status,
            "posted": False,
            "invoiced": False,
            "emailed": False,
            "vendor_shipment_no": shipment or None,
            "reasons": reasons,
            "warnings": warnings,
            "lines": assessment.get("lines") or [],
            "untouched_lines": assessment.get("untouched_lines") or [],
        }

    def _load(self, kind: str, value: str) -> dict:
        try:
            if kind == "guid":
                po = bc_client.get_purchase_order_with_lines(value)
            else:
                po = bc_client.get_purchase_order_by_number(value)
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code == 404:
                raise PurchaseOrderReceiveError(
                    404, f"Purchase order {value} not found in Business Central",
                ) from exc
            raise PurchaseOrderReceiveError(
                502, f"Failed to look up purchase order {value} in Business Central: {exc}",
            ) from exc
        if not po:
            raise PurchaseOrderReceiveError(
                404, f"Purchase order {value} not found in Business Central",
            )
        return po

    def _prior(self, db: Session, number: str, shipment: str) -> Optional[dict]:
        rows = (
            db.query(AuditTrail)
            .filter(
                AuditTrail.entity_type == "purchase_order",
                AuditTrail.entity_id == (number or "")[:50],
                AuditTrail.action.in_(_PRIOR_ACTIONS),
            )
            .order_by(AuditTrail.id.asc())
            .all()
        )
        found = None
        for row in rows:
            details = row.details or {}
            if not isinstance(details, dict):
                continue
            if (details.get("vendor_shipment_no") or "") != shipment:
                continue
            receipt = details.get("posted_receipt_no")
            if not receipt:
                continue
            found = {
                "posted_receipt_no": receipt,
                "posted_receipt_id": details.get("posted_receipt_id"),
                "lines": details.get("lines") or [],
                "released_for_receipt": bool(details.get("released_for_receipt")),
            }
            if row.action == "purchase_order_receive_received":
                return found
        return found

    def _audit(
        self,
        db: Session,
        *,
        actor: str,
        service_key_name: Optional[str],
        confirm: bool,
        dry_run: bool,
        po: dict,
        shipment: str,
        outcome: str,
        reasons: Sequence[dict],
        warnings: Sequence[dict],
        lines: Sequence[dict],
        posted_receipt_no: Optional[str] = None,
        posted_receipt_id: Optional[str] = None,
        released_for_receipt: bool = False,
    ) -> bool:
        when = datetime.utcnow().replace(microsecond=0)
        number = str(po.get("number") or "")
        try:
            db.add(AuditTrail(
                user_id=(actor or "")[:50],
                action=f"purchase_order_receive_{outcome}"[:100],
                entity_type="purchase_order",
                entity_id=number[:50],
                details={
                    "actor": actor,
                    "service_key_name": service_key_name,
                    "confirm": bool(confirm),
                    "dry_run": bool(dry_run),
                    "po_number": number,
                    "po_id": po.get("id"),
                    "vendor_number": po.get("vendorNumber"),
                    "api_status": po.get("status"),
                    "vendor_shipment_no": shipment or None,
                    "posted_receipt_no": posted_receipt_no,
                    "posted_receipt_id": posted_receipt_id,
                    "released_for_receipt": bool(released_for_receipt),
                    "invoiced": False,
                    "emailed": False,
                    "outcome": outcome,
                    "when": when.isoformat() + "Z",
                    "lines": list(lines),
                    "reasons": list(reasons),
                    "warnings": list(warnings),
                    "bc_action": PURCHASE_ORDER_RECEIVE_ACTION if outcome == "received" else None,
                },
                timestamp=when,
            ))
            db.commit()
            return True
        except Exception:
            logger.exception("Purchase order receive audit failed for %s", number)
            db.rollback()
            return False


po_receive_service = PurchaseOrderReceiveService()
